---
name: review
description: Check that every quote supports its sentence, fix warnings and finish the course with check_course. Use after writing sections.
---
# Review the course

1. For each written section, re-read the cited passages. A quote must state
   the fact in its sentence, not just share a word with it. Rewrite the
   section with `write_section`, dropping or correcting any sentence its
   quote does not support.
2. Call `check_course`:
   - `unwritten`: write those sections.
   - `untaught`: search the sources once more for those items; if nothing
     supports them, leave them as gaps.
   - `warnings`: fix each one by quoting the passage with the number, or
     removing the number.
3. Stop when `check_course` shows nothing left that the sources can support.
