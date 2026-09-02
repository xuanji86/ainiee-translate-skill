// Workflow 脚本模板：并行翻译的「翻译 → 验收 → 重派」流水线。
// 用法：主控先跑
//   <PFX> -m ainiee_translate.batch split work/cache.json --target 300 --out-dir work/par --context 20
//   for 每组: <PFX> -m ainiee_translate.glossary filter --locked work/glossary.locked.json --for work/par/grp_N_src.json --out work/par/g_N.json
// 然后 Workflow({ scriptPath: <本文件的副本>, args: { proj: "/abs/path/to/proj", skill: "/abs/path/to/skill", pfx: "PYTHONPATH=... python", groups: [1,2,3,...] } })
// 脚本只产出「哪些组已通过 validate」；写回、verify、scan、export 仍由主控串行执行。
export const meta = {
  name: 'ainiee-parallel-translate',
  description: 'Translate chapter groups in parallel, validate each, re-dispatch failures once',
  phases: [{ title: 'Translate' }, { title: 'Validate' }, { title: 'Retry' }],
}

const { proj, skill, pfx, groups } = args
const RESULT = {
  type: 'object',
  properties: {
    group: { type: 'number' },
    translated: { type: 'number' },
    validate_ok: { type: 'boolean' },
    hard: { type: 'array', items: { type: 'string' } },
    warnings: { type: 'object' },
    newterms: { type: 'array', items: { type: 'string' } },
  },
  required: ['group', 'translated', 'validate_ok'],
}

const translatePrompt = (n, retryNote) => `
你是文学译者，负责第 ${n} 组。先完整读：${proj}/work/STYLE_GUIDE.md、${proj}/work/BOOK_BIBLE.md（若存在）、
${proj}/work/par/g_${n}.json（本组词汇表）、${proj}/work/user_prompt.md（若有）、${skill}/references/translation_rules.md、
${proj}/work/par/grp_${n}_ctx.json（前文只读上下文）。
输入：${proj}/work/par/grp_${n}_src.json。逐段 1:1 翻译；每 30–50 段用 Python 把 {"text_index","translated_text"} 逐行
json.dumps(ensure_ascii=False) 追加到 ${proj}/work/par/trans_${n}.jsonl。人名/专名保留原文除非词汇表给了译名；<i>/<b> 标记成对保留；
对话引号用 “ ”；与中文相邻的标点全角。保留为英文的新专名写 ${proj}/work/par/newterms_${n}.txt（每行一个）。
译完跑：${pfx} -m ainiee_translate.batch validate ${proj}/work/par/grp_${n}_src.json ${proj}/work/par/trans_${n}.jsonl
hard 非空就修到退出码 0（删旧行再追加，或整文件重写）。绝不碰 cache.json、绝不跑 batch write。
${retryNote || ''}
返回 StructuredOutput：group、translated（段数）、validate_ok、hard（kind 列表）、warnings（类别→计数）、newterms。`

phase('Translate')
const results = await pipeline(
  groups,
  g => agent(translatePrompt(g), { label: `translate:grp${g}`, phase: 'Translate', schema: RESULT }),
  async (r, g) => {
    if (r && r.validate_ok) return r
    log(`grp ${g} failed validate (${r ? (r.hard || []).join(',') : 'no result'}); re-dispatching once`)
    return agent(translatePrompt(g,
      `上一轮 validate 未通过：${r ? JSON.stringify(r.hard) : 'agent 未返回'}。只需补齐/修正那些 index，其余已写行保持不动。`),
      { label: `retry:grp${g}`, phase: 'Retry', schema: RESULT })
  },
)

const ok = results.filter(Boolean).filter(r => r.validate_ok).map(r => r.group)
const failed = groups.filter(g => !ok.includes(g))
if (failed.length) log(`still failing after retry: ${failed.join(', ')} — fix by hand before writing`)
return {
  write_files: ok.map(g => `${proj}/work/par/trans_${g}.jsonl`),
  newterm_files: ok.map(g => `${proj}/work/par/newterms_${g}.txt`),
  failed,
  warnings: Object.fromEntries(results.filter(Boolean).map(r => [r.group, r.warnings || {}])),
}
