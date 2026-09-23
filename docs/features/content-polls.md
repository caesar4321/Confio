# Polls in Descubrir and Mensajes

In Portal → Publications, enable **Incluir encuesta**, enter a question and 2–10 distinct answers, and select Canal and/or Descubrir. Polls can accompany text, news, or video publications. Save and publish using the existing publication controls.

Each signed-in person gets one answer per publication, shared across accounts and surfaces. Selecting another answer replaces the previous vote while the poll is open. Repeated submissions do not add votes. The mobile client reveals results after the viewer votes or the poll closes, showing percentages and the viewer's selection, with counts in accessibility labels. Percentages are rounded independently.

Open a publication in Portal to see its totals; use **Actualizar resultados** to fetch the latest votes. **Encuesta cerrada** stops new votes and answer changes; unchecking it reopens voting. Once any vote exists, the server locks the question and option IDs/labels/order, including attempts to remove the poll through advanced metadata. Create another publication for a different question.

Poll configuration is stored in `ContentItem.metadata.poll` with `question`, `options: [{id, label}]`, and `closed`. Answers are stored separately in `ContentPollVote`, protected by a unique `(content_item, user)` constraint. Portal saves and votes lock the publication row to serialize edits, closure, and concurrent votes. Django admin publication and channel-inline saves preserve the latest poll under that same lock; manage polls in Portal. Feed and Portal vote totals are batched per page, with counted answers and their configuration read together. Voting requires published, accessible content and a valid account context.

Deploy the backend and run `python manage.py migrate` (includes `inbox.0012_contentpollvote`) before deploying the Portal and mobile client, which request the new `poll` GraphQL field. No production migration is run by this implementation task.

Tests use the project's PostgreSQL test environment:

- Backend: `python manage.py test inbox.test_polls inbox.test_poll_admin inbox.test_poll_concurrency inbox.tests.PortalContentMutationTests`
- Mobile: `cd apps && npm test -- --config jest.config.js --runInBand --watchman=false src/components/__tests__/ContentPoll.test.tsx src/components/__tests__/MessageInboxContent.polls.test.tsx`
- Portal: `cd web && CI=true npm test -- --watchAll=false --runInBand --watchman=false src/Components/Portal/PortalConsole.polls.test.js`

The mobile tests exercise shared cache results, duplicate taps, failed submissions, local reaction preservation, refresh after pagination, and a delayed page response after an account switch. PostgreSQL tests cover simultaneous votes and a first vote racing an option edit.
