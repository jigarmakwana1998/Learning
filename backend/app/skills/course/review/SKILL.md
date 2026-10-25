---
name: review
description: Check that every quote supports its sentence, fix every warning and finish the course with check_course. Use after writing sections.
---
# Review the course

1. Call `check_course`.
2. Fix every warning before you finish; each one is highlighted for the
   learner until you do:
   - "Fact with no citation": find the passage that states it and cite it.
     If no passage states it, remove the sentence.
   - "Quote not found": copy the quote again, character for character, from
     the one passage you cite.
   - A number warning: quote the passage that contains the number, or remove
     the number.
   Rewrite the whole section with `write_section`, keeping its correct
   sentences.
3. For each written section, re-read the cited passages. A quote must state
   every part of the fact in its sentence, not just share a topic with it.
   If it does not, cite a passage that does, reword the sentence to say only
   what the quote says, or remove it.
4. `unwritten`: write those sections. `untaught`: search the sources once
   more for those items; if nothing supports them, leave them as gaps.
5. Call `check_course` again. Finish only when it shows no warnings and
   nothing left that the sources can support.
