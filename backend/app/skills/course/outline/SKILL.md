---
name: outline
description: Plan the course's chapters and sections from the goal, coverage items and sources, then call set_outline. Use first.
---
# Outline the course

1. Call `list_sources` for the goal, the coverage items and the sources.
2. Size the course to the total hours and level: a short goal gets a few
   focused chapters, a long one gets more chapters with more sections each.
   Plan only what the sources can teach.
3. Order chapters so prerequisites come first. Each section has one learning
   goal and lists the coverage ids from `list_sources` it teaches in `covers`.
4. Every coverage item that has a source must be taught by some section.
5. Give every chapter and section a title and a short stable id such as `c1`
   and `c1-s2`. Each section id must be unique.
6. Call `set_outline` once with all chapters. Change the outline later only
   if the structure must change, and keep the ids of sections you keep:
   written sections are stored by id.
