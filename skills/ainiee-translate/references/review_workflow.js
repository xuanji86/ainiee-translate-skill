// Workflow 脚本模板：意义审（两个不同模型族各审一遍）→ 合并 → 编辑出补丁。
// 用法：主控先跑
//   <PFX> -m ainiee_translate.batch split work/cache.json --stage review --range A-B --target 130 --prefix h --out-dir work/dual
//   （复审只看改过的段：再加 --changed-since work/cache.json.pre_xxx）
//   <PFX> -m ainiee_translate.batch bundle work/cache.json work/dual/grp_h*_src.json --stage review --include work/user_prompt.md
// 然后 Workflow({ scriptPath: <本文件的副本>, args: { proj, pfx, groups: ["h1","h2",…],
//                 reviewers: ["opus","fable"], editor: "opus", editorBatch: 90 } })
// 返回补丁文件清单；主控执行 batch apply … --source dual，再 verify/audit/export。
export const meta = {
  name: 'ainiee-dual-review',
  description: 'Two model families review each group independently, merge by agreement, an editor writes patches',
  phases: [{ title: 'Review' }, { title: 'Merge' }, { title: 'Edit' }],
}

const { proj, pfx, groups, reviewers, editor, editorBatch } = args
const dir = `${proj}/work/dual`
const DONE = { type: 'object', properties: { count: { type: 'number' }, sev2: { type: 'number' } }, required: ['count'] }
const reviewPrompt = (g, who) =>
  `你是出版级英译中审校。读 ${dir}/bundle_${g}.md（只读这一个文件），照「交付」一节审稿，` +
  `结果一次 Write 到 ${dir}/${who}_${g}.jsonl。不改其他文件。返回 StructuredOutput：count、sev2。`

phase('Review')
await parallel(groups.flatMap(g => reviewers.map(who => () =>
  agent(reviewPrompt(g, who), { label: `review:${who}:${g}`, phase: 'Review', schema: DONE, model: who }))))

phase('Merge')
const files = groups.flatMap(g => reviewers.map(who => `${dir}/${who}_${g}.jsonl`))
const merged = await agent(
  `只跑这一条命令，原样返回它最后一行的 JSON：\n` +
  `${pfx} -m ainiee_translate.review dual-merge ${proj}/work/cache.json ${files.join(' ')} --out ${dir}/fix_input.json`,
  { label: 'dual-merge', phase: 'Merge', model: 'haiku' })
log(`merged: ${merged}`)

phase('Edit')
const n = Math.max(1, Math.ceil(groups.length * 130 / (editorBatch || 90) / 2))
const EDIT = { type: 'object', properties: { changed: { type: 'number' }, rejected: { type: 'number' } }, required: ['changed'] }
const editPrompt = k =>
  `你是终审编辑。读 ${proj}/work/user_prompt.md 与 ${dir}/fix_input.json（按 agree 降序；只处理下标 i % ${n} == ${k} 的条目）。` +
  `agree=2 的几乎都成立；agree=1 的自己核原文再定；与规则卡（state card）冲突的一律驳回。` +
  `成立的只改出问题的那部分：一次 Write 到 ${dir}/patches_${k}.jsonl，每段一行 ` +
  `{"text_index": N, "patches": [["原句片段","新片段"], …], "reason": "一句话"}（片段须在 current 里恰好出现一次）；` +
  `驳回的写 ${dir}/rejected_${k}.jsonl：{"i":N,"by":"…","issue":"…","reason":"…"}。返回 StructuredOutput：changed、rejected。`
const edits = await parallel([...Array(n).keys()].map(k => () =>
  agent(editPrompt(k), { label: `edit:${k}`, phase: 'Edit', schema: EDIT, model: editor })))
return { patch_files: [...Array(n).keys()].map(k => `${dir}/patches_${k}.jsonl`), edits }
