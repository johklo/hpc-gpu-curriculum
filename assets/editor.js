/* 페이지 안에서 문단을 고치고 GitHub에 바로 저장한다.
 *
 * 정적 사이트라 서버가 없다. 저장은 브라우저가 GitHub Contents API를 직접 부르는 방식으로
 * 한다. 토큰은 이 브라우저의 localStorage에만 두고 api.github.com 외에는 보내지 않는다.
 */
(function () {
  "use strict";

  var shell = document.querySelector(".shell");
  if (!shell) return;
  var REPO = shell.getAttribute("data-repo");
  var BRANCH = shell.getAttribute("data-branch") || "main";
  var KEY = "hpc-handbook-token";
  var API = "https://api.github.com";

  function token() { return localStorage.getItem(KEY) || ""; }

  function askToken() {
    var msg =
      "저장하려면 GitHub 토큰이 필요하다.\n\n" +
      "github.com/settings/personal-access-tokens 에서 이 저장소만 대상으로\n" +
      "Contents: Read and write 권한을 준 토큰을 만들어 붙여넣는다.\n\n" +
      "토큰은 이 브라우저에만 저장되고 GitHub 외에는 전송하지 않는다.";
    var value = window.prompt(msg, "");
    if (value) { localStorage.setItem(KEY, value.trim()); return true; }
    return false;
  }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign({
      "Authorization": "Bearer " + token(),
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28"
    }, options.headers || {});
    return fetch(API + path, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.message || ("HTTP " + response.status));
        return data;
      });
    });
  }

  function decode(base64) {
    var binary = atob(base64.replace(/\n/g, ""));
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return new TextDecoder("utf-8").decode(bytes);
  }

  function encode(text) {
    var bytes = new TextEncoder().encode(text);
    var binary = "";
    for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  // 문서 전체에서 해당 문단의 본문 구간만 찾아 바꾼다. 저장 직전에 최신 파일을 다시
  // 받아오므로 다른 사람이 먼저 고친 내용을 덮어쓰지 않는다.
  function replaceSection(source, heading, body) {
    var lines = source.split("\n");
    var start = -1, end = lines.length;
    for (var i = 0; i < lines.length; i++) {
      if (start === -1) {
        if (lines[i].replace(/^##\s+/, "") === heading && /^##\s+/.test(lines[i])) start = i + 1;
      } else if (/^##\s+/.test(lines[i])) { end = i; break; }
    }
    if (start === -1) return null;
    return lines.slice(0, start).concat("", body.trim(), "").concat(lines.slice(end)).join("\n");
  }

  function open(section) {
    if (section.querySelector(".editor")) return;
    var source = section.querySelector(".sec-src").textContent;
    var bodyNode = section.querySelector(".sec-body");
    var heading = section.getAttribute("data-heading");
    var file = section.getAttribute("data-file");

    var editor = document.createElement("div");
    editor.className = "editor";
    editor.innerHTML =
      '<textarea class="editor-area" spellcheck="false"></textarea>' +
      '<div class="editor-bar">' +
      '<button type="button" data-act="save" class="btn-main">저장</button>' +
      '<button type="button" data-act="cancel">취소</button>' +
      '<span class="editor-msg" role="status"></span>' +
      '<span class="editor-hint">Markdown으로 쓴다. 저장하면 변경 이력이 남는다.</span>' +
      "</div>";
    var area = editor.querySelector(".editor-area");
    area.value = source;
    bodyNode.hidden = true;
    section.querySelector(".sec-alt").hidden = true;
    bodyNode.parentNode.insertBefore(editor, bodyNode.nextSibling);
    area.style.height = Math.max(220, area.scrollHeight + 20) + "px";
    area.focus();

    var msg = editor.querySelector(".editor-msg");
    var say = function (text, kind) {
      msg.textContent = text || "";
      msg.setAttribute("data-kind", kind || "");
    };

    var close = function () {
      editor.remove();
      bodyNode.hidden = false;
      section.querySelector(".sec-alt").hidden = false;
      section.querySelector('[data-act="edit"]').textContent = "고치기";
    };

    editor.addEventListener("click", function (event) {
      var act = event.target.getAttribute("data-act");
      if (act === "cancel") { close(); return; }
      if (act !== "save") return;

      if (!token() && !askToken()) return;
      var body = area.value;
      if (body.trim() === source.trim()) { say("바뀐 내용이 없다.", "warn"); return; }

      say("저장하는 중…");
      event.target.disabled = true;

      api("/repos/" + REPO + "/contents/content/" + file + "?ref=" + BRANCH)
        .then(function (data) {
          var updated = replaceSection(decode(data.content), heading, body);
          if (updated === null) throw new Error("문단을 찾지 못했다: " + heading);
          return api("/repos/" + REPO + "/contents/content/" + file, {
            method: "PUT",
            body: JSON.stringify({
              message: "문서 수정: " + heading,
              content: encode(updated),
              sha: data.sha,
              branch: BRANCH
            })
          });
        })
        .then(function () {
          say("저장했다. 1분쯤 뒤 사이트에 반영된다.", "ok");
          section.querySelector(".sec-src").textContent = body;
          setTimeout(close, 1800);
        })
        .catch(function (error) {
          event.target.disabled = false;
          var text = String(error.message || error);
          if (/Bad credentials|401/.test(text)) {
            localStorage.removeItem(KEY);
            say("토큰이 거부됐다. 다시 저장을 누르면 새로 입력한다.", "err");
          } else if (/404/.test(text) || /Not Found/.test(text)) {
            say("저장소에 쓸 권한이 없다. 토큰 범위를 확인한다.", "err");
          } else {
            say(text, "err");
          }
        });
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest('[data-act="edit"]');
    if (!button) return;
    var section = button.closest(".sec");
    if (section.querySelector(".editor")) {
      section.querySelector('[data-act="cancel"]').click();
    } else {
      button.textContent = "편집 중";
      open(section);
    }
  });

  // 토큰을 지우는 통로. 공용 PC에서 쓴 경우를 위해 열어 둔다.
  var reset = document.getElementById("token-reset");
  if (reset) {
    reset.addEventListener("click", function (event) {
      event.preventDefault();
      localStorage.removeItem(KEY);
      reset.textContent = "토큰을 지웠다";
    });
  }
})();
