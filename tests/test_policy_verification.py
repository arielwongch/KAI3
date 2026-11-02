"""Policy invariants introduced by the audit implementation, with injected models."""
from copy import deepcopy
import os
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,'src')
os.environ.setdefault('DEEPSEEK_API_KEY','test-only')
import Benchmark
from AuditProvenance import memory_identity
from Diagnostics import retrieval_collector
from MemoryContext import build_memory_context, format_context, WINDOW_PACKING_POLICY
from MemoryEntry import MemoryEntry
from ResultAnalysis import lifecycle_metrics
from VectorStoreReranker import VectorStoreReranker
from benchmark_helpers import FakeTokenizer
from test_controlled_comparison import dataset
from test_semantic_memory import FakeEmbeddings


class PolicyVerificationTests(unittest.TestCase):
    def test_tight_budget_recency_historical_guidance_and_omissions(self):
        recent=lambda text:MemoryEntry(text,dict(memory_tier='recent',memory_component='sliding_window'))
        old=MemoryEntry('Former home Rome. '*60,dict(memory_tier='long_term',memory_component='summarization'))
        records=[old,recent('Earlier turn'),recent('Current home Paris.')]
        module=Mock(packing_policy=WINDOW_PACKING_POLICY)
        module.iter_context_candidates.return_value=records
        before=deepcopy(records)
        budget=len(format_context([records[-1]]))
        for question in ('Where now?','Where previously?'):
            packed=build_memory_context(module,question,budget,FakeTokenizer(),2)
            self.assertEqual(packed['entries'],[records[-1]])
            self.assertIn('For historical questions',packed['text'])
            self.assertEqual(packed['tiers']['recent']['omitted_count'],1)
            self.assertEqual(packed['tiers']['long_term']['oversized_count'],1)
        large=build_memory_context(module,'When?',10000,FakeTokenizer())
        self.assertEqual(large['entries'],records)
        self.assertEqual(records,before)
        tiny=build_memory_context(module,'Where?',1,FakeTokenizer())
        self.assertEqual(tiny['entries'],[])
        self.assertTrue(tiny['all_candidates_over_budget'])
        module.iter_context_candidates.return_value=[]
        self.assertEqual(build_memory_context(module,'?',1,FakeTokenizer())['tiers']['recent']['candidate_count'],0)

    def test_resume_rejects_previous_window_packing(self):
        with patch.object(Benchmark,'get_benchmark_tokenizer',return_value=FakeTokenizer()):
            job=Benchmark.BenchmarkJob(dataset(1),dict(module='alpha'))
            previous=job.snapshot()
            previous['packing_policy']='whole-record-first-k-greedy-v1'
            with self.assertRaisesRegex(ValueError,'packing_policy'):
                Benchmark.BenchmarkJob.resume(dataset(1),previous)

    def test_pool_final_and_packed_records_remain_distinct(self):
        reranker=Mock(identity={'model':'injected'},score=Mock(return_value=[1,5,2]))
        store=VectorStoreReranker(embedder=FakeEmbeddings(),candidate_k=3,reranker=reranker)
        for i in range(3): store.write(MemoryEntry('cat '+str(i),dict(dialogue_id=str(i))))
        before=memory_identity(store)
        metrics={}
        token=retrieval_collector.set(metrics)
        try: packed=build_memory_context(store,'cat',5,FakeTokenizer(),2)
        finally: retrieval_collector.reset(token)
        traces={t['stage']:t for t in metrics['retrieval_traces']}
        self.assertEqual(len(traces['reranker_pool']['records']),3)
        self.assertEqual(len(traces['reranked_final']['records']),2)
        self.assertEqual(len(packed['entries']),1)
        self.assertEqual(traces['reranker_pool']['records'][0]['score'],1.0)
        self.assertEqual(traces['reranked_final']['records'][0]['score'],5)
        self.assertEqual(memory_identity(store),before)

    def test_lifecycle_deduplicates_builds_and_preserves_unknown_usage(self):
        build=dict(module='vector_store',ingestion=dict(ingestion_id='one',memory_tokens=10,total_seconds=2))
        report=dict(memories=[build],previous_ingestions=[deepcopy(build)])
        cases=[dict(diagnostics=dict(answer_tokens=20,judge_tokens=3,total_seconds=4,retrieval_seconds=.5))]
        metrics=lifecycle_metrics(report,'vector_store',cases)
        self.assertEqual(metrics['ingestion_count'],1)
        self.assertEqual(metrics['total_provider_tokens'],33)
        self.assertEqual(metrics['total_seconds'],6)
        cases[0]['diagnostics']['answer_tokens']=None
        self.assertIsNone(lifecycle_metrics(report,'vector_store',cases)['total_provider_tokens'])
        report['previous_ingestions'][0]['ingestion']['memory_tokens']=11
        metrics=lifecycle_metrics(report,'vector_store',cases)
        self.assertTrue(metrics['conflicting_ingestion_ids'])
        self.assertIsNone(metrics['ingestion']['tokens'])
        self.assertIsNone(metrics['ingestion_seconds'])
