# Reasoning-mode route proposal1 independent QA

Result: **FAIL_BOUNDED_PROPOSAL**. Eleven of14 offline cases passed. The original12-case suite already catches `/samtec/private`; two additional original-validation cases `/samtec/nonsense` and `/samtec/job/abc/extra` also fail.

The proposal now correctly tests the tenant slug and preserves other employers. However, the Samtec branch bypasses the original invalid-scope rejection, accepting arbitrary Samtec paths. Exact SHA, unique old text and syntax pass. Native response ended stop rather than length;1244 prompt tokens,999 output tokens,76.35seconds. No reasoning text is returned. No source edits applied.

Comparison caveat: original messages and tool schema exactly match non-thinking probe1, but output ceiling increased from1000 to3072 tokens. This is a bounded configuration comparison, not an isolated causal estimate of thinking mode. The observed correction of routing mistakes does not establish reliability; original input validation still fails.
