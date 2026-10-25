---
name: review
description: Check that every quote supports its sentence, fix warnings and finish the course with check_course. Use after writing sections.
---
# Review the course

1. For each written section, re-read the cited passages. A quote must state
   every part of the fact in its sentence, not just share a topic with it.
   If it does not, cite a passage that does, reword the sentence to say only
   what the quote says, or drop it. Save the section again with
   `write_section`.
2. Call `check_course`:
   - `unwritten`: write those sections.
   - `untaught`: search the sources once more for those items; if nothing
     supports them, leave them as gaps.
   - `warnings`: fix each one as the write skill describes.
3. Stop when `check_course` shows nothing left that the sources can support.
