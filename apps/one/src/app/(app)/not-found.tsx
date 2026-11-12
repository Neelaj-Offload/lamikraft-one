import { Page } from "~/shell/page";
import { ButtonLink } from "~/ui/button";
import { EmptyState } from "~/ui/empty-state";

export default function AppNotFound() {
  return (
    <Page width="narrow">
      <EmptyState
        icon="search"
        title="That page is not here"
        text="The link may be out of date, or the record was removed. Search for it, or start again from today's work."
        actions={
          <>
            <ButtonLink href="/today" variant="inverse">
              Back to Today
            </ButtonLink>
            <ButtonLink href="/search" variant="ghost">
              Search
            </ButtonLink>
          </>
        }
      />
    </Page>
  );
}
