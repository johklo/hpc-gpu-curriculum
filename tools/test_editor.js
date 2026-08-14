// Check that section replacement ignores `## ` lines inside fenced code blocks.
const fs = require("fs");
const path = require("path");

const src = fs.readFileSync(path.join(__dirname, "..", "assets", "editor.js"), "utf8");
const start = src.indexOf("function isHeading");
const end = src.indexOf("function open(");
eval(src.slice(start, end));

const doc = [
  "## 첫 절", "본문 A", "",
  "## 리포트", "앞말", "```markdown", "# 제목", "## 증상", "- 내용", "## 원인", "- 내용", "```", "뒷말", "",
  "## 끝 절", "본문 B", "",
].join("\n");

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? "통과" : "실패"}  ${label}`);
}

const replaced = replaceSection(doc, "리포트", "새 본문");
check("리포트 본문이 교체된다", replaced.includes("새 본문"), true);
check("리포트 안의 코드블록은 함께 사라진다", replaced.includes("```markdown"), false);
check("앞 절이 남는다", replaced.includes("본문 A"), true);
check("뒤 절이 남는다", replaced.includes("본문 B"), true);
check("뒤 절 제목이 남는다", replaced.includes("## 끝 절"), true);

const first = replaceSection(doc, "첫 절", "교체됨");
check("첫 절만 고치면 코드블록이 보존된다", first.includes("```markdown") && first.includes("## 증상"), true);
check("첫 절만 고치면 리포트 절이 통째로 남는다", first.includes("앞말") && first.includes("뒷말"), true);
check("첫 절만 고치면 끝 절도 남는다", first.includes("본문 B"), true);

const stray = replaceSection(doc, "증상", "안 된다");
check("코드블록 안의 제목은 절로 잡히지 않는다", stray, null);

console.log(failures === 0 ? "\n전부 통과" : `\n실패 ${failures}건`);
process.exit(failures === 0 ? 0 : 1);
