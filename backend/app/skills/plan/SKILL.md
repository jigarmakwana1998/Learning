---
name: plan
description: Decide what the topic must cover, record it with set_coverage, and write the first search queries. Use first, before any search.
---
# Plan the coverage

1. Size the coverage to the topic, the learner level and the total study hours. A
   short course needs the essentials; a longer or advanced one needs more depth.
2. Together the items should cover prerequisites and vocabulary; the central
   concepts or components; the process or mechanism; worked application;
   limitations, failure modes or misconceptions; and integration or informed
   decision-making. Add implementation, evaluation, variants or current practice
   when a longer or advanced course needs them.
3. Make the items complementary and non-overlapping. Give each a short id and a
   question the pages must answer.
4. Call `set_coverage` with every item and status `missing`.
5. Write one focused query per item, most important first. Put the topic's exact
   terms in every query, target one item, and name the source form likely to
   answer it: official documentation, specification, primary paper, worked
   example or case study. Avoid vague tutorial queries, near-duplicate
   paraphrases and queries made only from the learner level.
