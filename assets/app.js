(function () {
  "use strict";

  var tops = Array.prototype.slice.call(document.querySelectorAll(".rail-top"));
  var modules = Array.prototype.slice.call(document.querySelectorAll(".module"));
  var sections = Array.prototype.slice.call(document.querySelectorAll(".sec"));
  var search = document.getElementById("q");
  var toggle = document.querySelector(".rail-toggle");
  var nav = document.querySelector(".rail-nav");

  // 읽고 있는 모듈을 목차에 표시한다. 스크롤 이벤트 대신 관찰자를 쓴다.
  if ("IntersectionObserver" in window && modules.length) {
    var ratios = {};
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        ratios[entry.target.id] = entry.isIntersecting ? entry.intersectionRatio : 0;
      });
      var best = "", top = 0;
      Object.keys(ratios).forEach(function (id) {
        if (ratios[id] > top) { top = ratios[id]; best = id; }
      });
      tops.forEach(function (link) {
        link.setAttribute("aria-current", link.getAttribute("href") === "#" + best ? "true" : "false");
      });
    }, { rootMargin: "-10% 0px -70% 0px", threshold: [0, 0.2, 0.5, 1] });
    modules.forEach(function (module) { observer.observe(module); });
  }

  // 검색은 절 단위로 거른다. 남는 절이 없는 모듈과 목차 항목은 함께 접는다.
  if (search) {
    search.addEventListener("input", function () {
      var term = search.value.trim().toLowerCase();
      var kept = {};

      sections.forEach(function (section) {
        var hit = !term || (section.getAttribute("data-search") || "").indexOf(term) !== -1;
        section.classList.toggle("hidden", !hit);
        var id = section.closest(".module").id;
        kept[id] = (kept[id] || 0) + (hit ? 1 : 0);
      });

      modules.forEach(function (module) {
        module.classList.toggle("hidden", term !== "" && !kept[module.id]);
      });

      tops.forEach(function (link) {
        var id = link.getAttribute("href").slice(1);
        link.parentElement.classList.toggle("hidden", term !== "" && !kept[id]);
      });

      document.querySelectorAll(".rail-sub a").forEach(function (link) {
        var target = document.querySelector(link.getAttribute("href"));
        link.parentElement.classList.toggle("hidden", !!(target && target.classList.contains("hidden")));
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
    var narrow = window.matchMedia("(max-width:900px)");
    setOpen(!narrow.matches);
    narrow.addEventListener("change", function (event) { setOpen(!event.matches); });
    toggle.addEventListener("click", function () {
      setOpen(nav.getAttribute("data-collapsed") === "true");
    });
  }
})();
