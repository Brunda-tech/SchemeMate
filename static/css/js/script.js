(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const steps = document.querySelectorAll(".how-it-works .step");

    if (reducedMotion || !("IntersectionObserver" in window) || steps.length === 0) {
        return;
    }

    document.documentElement.classList.add("motion-ready");

    const observer = new IntersectionObserver((entries, currentObserver) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("is-visible");
                currentObserver.unobserve(entry.target);
            }
        });
    }, { threshold: 0.18 });

    steps.forEach((step) => observer.observe(step));
})();