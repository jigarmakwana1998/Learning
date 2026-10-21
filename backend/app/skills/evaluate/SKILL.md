---
name: evaluate
description: Judge how well the saved pages cover each item, update set_coverage, and decide the next search or stop. Use after saving pages.
---
# Evaluate coverage

1. Judge each item using only the pages you saved for it.
2. An item is `covered` only when its pages support a definition, a causal or
   procedural explanation, and an example, decision or boundary at the learner's
   level. One page mentioning a key term is not enough. Use `partial` when some
   of that is missing, `missing` when nothing supports it.
3. Call `set_coverage` with every item and its updated status.
4. For each gap, write one focused query that targets exactly what is missing,
   then search again.
5. Stop when every item is covered or the browser budget is exhausted. Never
   reward source count or source-type variety by itself.
