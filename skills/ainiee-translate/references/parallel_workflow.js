// Workflow 脚本模板：并行翻译「bundle 一次读写 → 主控验收 → 失败组重派一次」。
// 用法：主控先跑
//   <PFX> -m ainiee_translate.scan work/cache.json --locked work/glossary.locked.json --mode pending   # 新词先定名进表
//   <PFX> -m ainiee_translate.batch split work/cache.json --target 300 --out-dir work/par --context 20
//   <PFX> -m ainiee_translate.batch bundle work/cache.json work/par/grp_*_src.json --include work/user_prompt.md
// 然后 Workflow({ scriptPath: <本文件的副本>, args: { proj: "/abs/path/to/proj", pfx: "PYTHONPATH=... python",
//                 groups: ["1","2",...], model: "opus" } })
// agent 只读 bundle、只写 trans_N.jsonl + newterms_N.txt；验收由一个便宜的 agent 跑 validate（不动 cache.json）。
// 脚本返回通过的文件清单；merge-newterms 预览（查 CONFLICT）、batch write、verify/scan、export 仍由主控执行。
export const meta = {
  name: 'ainiee-parallel-translate',
  description: 'Translate chapter groups from read-once bundles, validate each, re-dispatch failures once',
  phases: [{ title: 'Translate' }, { title: 'Validate' }, { title: 'Retry' }],
}

const { proj, pfx, groups, model } = args
const par = `${proj}/work/par`
const TRANS = {
  type: 'object',
  properties: { group: { type: 'string' }, segments: { type: 'number' }, newterms: { type: 'number' },
                unsure: { type: 'array', items: { type: 'string' } } },
  required: ['group', 'segments'],
}
const CHECK = {
  type: 'object',
  properties: { group: { type: 'string' }, ok: { type: 'boolean' }, hard: { type: 'array', items: { type: 'string' } } },
  required: ['group', 'ok'],
}

// 共用部分放最前、逐字相同：并行 agent 更容易命中 prompt 缓存。
const translatePrompt = (g, note) =>
  `你是出版级文学译者。读 ${par}/bundle_${g}.md（只读这一个文件），照其中的「交付」一节执行：` +
  `一次 Write 写出全部译文与新词，不回读、不自校、不跑命令，绝不碰 cache.json。` +
  `${note ? '\n' + note : ''}\n返回 StructuredOutput：group="${g}"、segments、newterms、unsure（≤5 条「段号：一句话」）。`

const checkPrompt = g =>
  `只跑这一条命令并据输出返回结果，不改任何文件：\n` +
  `${pfx} -m ainiee_translate.batch validate ${par}/grp_${g}_src.json ${par}/trans_${g}.jsonl --cache ${proj}/work/cache.json\n` +
  `返回 StructuredOutput：group="${g}"、ok（退出码 0）、hard（hard 里每项的 kind，segment 类附段号）。`

phase('Translate')
const results = await pipeline(
  groups,
  g => agent(translatePrompt(g), { label: `translate:${g}`, phase: 'Translate', schema: TRANS, model }),
  async (r, g) => {
    const v = await agent(checkPrompt(g), { label: `validate:${g}`, phase: 'Validate', schema: CHECK, model: 'haiku' })
    if (v && v.ok) return { ...r, ok: true }
    log(`${g} failed validate: ${v ? (v.hard || []).join(', ') : 'no result'} — re-dispatching once`)
    const r2 = await agent(translatePrompt(g, `上一轮 validate 未通过：${v ? JSON.stringify(v.hard) : '无结果'}。` +
      `只修这些段：读 bundle 与已写的 trans_${g}.jsonl，整文件重写一次。`),
      { label: `retry:${g}`, phase: 'Retry', schema: TRANS, model })
    const v2 = await agent(checkPrompt(g), { label: `revalidate:${g}`, phase: 'Retry', schema: CHECK, model: 'haiku' })
    return { ...r2, ok: !!(v2 && v2.ok) }
  },
)

const ok = results.filter(r => r && r.ok).map(r => r.group)
const failed = groups.filter(g => !ok.includes(g))
if (failed.length) log(`still failing after retry: ${failed.join(', ')} — fix by hand before writing`)
return {
  write_files: ok.map(g => `${par}/trans_${g}.jsonl`),
  newterm_files: ok.map(g => `${par}/newterms_${g}.txt`),
  unsure: Object.fromEntries(results.filter(Boolean).map(r => [r.group, r.unsure || []])),
  failed,
}
