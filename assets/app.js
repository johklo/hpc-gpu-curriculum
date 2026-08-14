(function () {
  "use strict";

  var links = Array.prototype.slice.call(document.querySelectorAll(".rail-nav a"));
  var modules = Array.prototype.slice.call(document.querySelectorAll(".module"));
  var search = document.getElementById("q");
  var toggle = document.querySelector(".rail-toggle");
  var nav = document.querySelector(".rail-nav");

  // Mark the module currently being read. IntersectionObserver keeps this off the
  // scroll thread; without it the rail would need a listener on every frame.
  if ("IntersectionObserver" in window && modules.length) {
    var visible = new Map();
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        visible.set(entry.target.id, entry.isIntersecting ? entry.intersectionRatio : 0);
      });
      var best = "", ratio = 0;
      visible.forEach(function (value, key) {
        if (value > ratio) { ratio = value; best = key; }
      });
      links.forEach(function (link) {
        link.setAttribute("aria-current", link.getAttribute("href") === "#" + best ? "true" : "false");
      });
    }, { rootMargin: "-12% 0px -70% 0px", threshold: [0, 0.25, 0.5, 1] });
    modules.forEach(function (module) { observer.observe(module); });
  }

  // Filter the reading lists. Modules with no surviving entry step aside so the
  // page never shows an empty heading with nothing under it.
  if (search) {
    var entries = Array.prototype.slice.call(document.querySelectorAll("ol.entries li"));
    search.addEventListener("input", function () {
      var term = search.value.trim().toLowerCase();
      var perModule = {};

      entries.forEach(function (entry) {
        var hit = !term || (entry.getAttribute("data-search") || "").indexOf(term) !== -1;
        entry.classList.toggle("hidden", !hit);
        var id = entry.closest(".module").id;
        perModule[id] = (perModule[id] || 0) + (hit ? 1 : 0);
      });

      modules.forEach(function (module) {
        var count = perModule[module.id] || 0;
        module.classList.toggle("hidden", term !== "" && count === 0);
        var note = module.querySelector(".empty");
        if (note) note.classList.toggle("hidden", count !== 0);
      });

      links.forEach(function (link) {
        var id = link.getAttribute("href").slice(1);
        link.parentElement.classList.toggle("hidden", term !== "" && !(perModule[id] || 0));
        var badge = link.querySelector(".c");
        if (badge) badge.textContent = term ? (perModule[id] || 0) : badge.getAttribute("data-total");
      });
    });
  }

  if (toggle && nav) {
    var setOpen = function (open) {
      nav.setAttribute("data-collapsed", open ? "false" : "true");
      if (search) search.setAttribute("data-collapsed", open ? "false" : "true");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.textContent = open ? "목차 닫기" : "목차 열기";
    };
    var mobile = window.matchMedia("(max-width:900px)");
    setOpen(!mobile.matches);
    mobile.addEventListener("change", function (event) { setOpen(!event.matches); });
    toggle.addEventListener("click", function () {
      setOpen(nav.getAttribute("data-collapsed") === "true");
    });
  }
})();
