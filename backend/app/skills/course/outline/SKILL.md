---
name: outline
description: Plan the course's chapters and sections from the goal, coverage items and sources, then call set_outline. Use first.
---
# Outline the course

1. Call `list_sources` for the goal, the coverage items and the sources.
2. Choose the depth and number of sections that fit the goal and learner level.
   Ask Researcher for sources when an important topic needs more information.
3. Order chapters so prerequisites come first. Each section has one learning
   goal and lists the coverage ids from `list_sources` it teaches in `covers`.
4. Use coverage items as planning guidance, adjusting the outline as you learn.
5. Give every chapter and section a title and a short stable id such as `c1`
   and `c1-s2`. Each section id must be unique.
6. Call `set_outline` once with all chapters. Change the outline later only
   if the structure must change, and keep the ids of sections you keep:
   written sections are stored by id.
