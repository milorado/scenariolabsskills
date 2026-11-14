import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

for (const mode of ["staged", "unstaged", "mixed", "check"]) {
  test(`dictionary sorting preserves ${mode} selection`, (t) => {
    const root = mkdtempSync(join(tmpdir(), "skills-words-"));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    mkdirSync(join(root, "scripts"));
    copyFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "sort-project-words.sh"),
      join(root, "scripts/sort-project-words.sh"),
    );
    const git = (...args) =>
      execFileSync("git", args, { cwd: root, encoding: "utf8" });
    git("init", "-q");
    writeFileSync(join(root, "project-words.txt"), "apple\n");
    git("add", "project-words.txt");
    git(
      "-c",
      "user.name=Test",
      "-c",
      "user.email=test@example.invalid",
      "commit",
      "-qm",
      "fixture",
    );
    const words = join(root, "project-words.txt");
    writeFileSync(words, "banana\napple\n");
    if (mode !== "unstaged") git("add", "project-words.txt");
    if (mode === "mixed") writeFileSync(words, "banana\napple\ncherry\n");
    const before = readFileSync(words, "utf8");
    const staged = git("show", ":project-words.txt");
    const result = spawnSync(
      "bash",
      [
        "scripts/sort-project-words.sh",
        ...(mode === "check" ? ["--check"] : []),
      ],
      { cwd: root, encoding: "utf8" },
    );
    if (mode === "mixed" || mode === "check") {
      assert.notEqual(result.status, 0);
      assert.equal(readFileSync(words, "utf8"), before);
      assert.equal(git("show", ":project-words.txt"), staged);
    } else {
      assert.equal(result.status, 0, result.stderr);
      assert.equal(readFileSync(words, "utf8"), "apple\nbanana\n");
      assert.equal(
        git("show", ":project-words.txt"),
        mode === "staged" ? "apple\nbanana\n" : "apple\n",
      );
    }
  });
}
