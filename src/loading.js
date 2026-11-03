/* Small, shared indicators. Counts keep overlapping work from clearing each other. */
globalThis.KAI3Loading ||= (() => {
    const pending = new WeakMap();
    function begin(...targets) {
        const elements = [...new Set(targets.flat().filter(Boolean))];
        for (const element of elements) {
            const state = pending.get(element) || {count: 0, busy: element.getAttribute('aria-busy')};
            state.count++;
            pending.set(element, state);
            element.setAttribute('data-loading', 'true');
            element.setAttribute('aria-busy', 'true');
        }
        let finished = false;
        return () => {
            if (finished) return;
            finished = true;
            for (const element of elements) {
                const state = pending.get(element);
                if (--state.count) continue;
                pending.delete(element);
                element.removeAttribute('data-loading');
                if (state.busy == null) element.removeAttribute('aria-busy');
                else element.setAttribute('aria-busy', state.busy);
            }
        };
    }
    async function during(targets, work) {
        const finish = begin(targets);
        try { return await work(); }
        finally { finish(); }
    }
    function bind(element, event, targets) {
        const handler = element[event];
        element[event] = function (...args) {
            return during(targets, () => handler.apply(this, args));
        };
    }
    return {begin, during, bind};
})();
