"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { isBlankRow } from "@/features/cutting/editor-model";
import { asRoute, usePlanEditor } from "~/data/cutting";
import { Steps, type StepState } from "~/screens/sales/quotations/parts";
import { Page, PageHeader } from "~/shell/page";
import { Banner, Button, ButtonLink, FormActions, GlassPanel } from "~/ui";
import { BoardSection, NameSection, PiecesSection } from "./plan-form";
import { stagger } from "./parts";

/** The oversize allowance the company works with, until the saved plan reports its own. */
const DEFAULT_OVERSIZE_MM = "10";

/**
 * Start a cut plan: the pieces, then the board. The plan opens as a draft, where the layout is
 * calculated. Three blank rows and the company's standard board are filled in to begin with.
 */
export function PlanNew() {
  const router = useRouter();
  const editor = usePlanEditor(null);
  const [step, setStep] = useState<0 | 1>(0);

  const pieceCount = editor.form.rows.filter((row) => !isBlankRow(row)).length;
  const piecesNeedAttention = Boolean(editor.errors.name) || Object.keys(editor.errors.rows).length > 0 || editor.errors.general.length > 0;

  const toBoard = () => {
    const errors = editor.check();
    if (errors.name || Object.keys(errors.rows).length > 0) return;
    setStep(1);
  };

  const create = async () => {
    const saved = await editor.save();
    if (saved) router.replace(asRoute(saved.path));
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (step === 0) toBoard();
    else void create();
  };

  const stateOf = (index: number): StepState => (index < step ? "done" : index === step ? "current" : "todo");

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: "Operations", href: "/operations" }, { label: "Cut plans", href: "/operations/cutting" }, { label: "New" }]}
        title="New cut plan"
        lead="List what you need cut, then say which board it comes from. The layout is calculated once the draft is saved."
      />

      <GlassPanel padding="md" className="rise" style={stagger(1)}>
        <Steps
          label="Steps to a draft cut plan"
          steps={[
            { id: "pieces", label: "Pieces", hint: step > 0 ? (pieceCount === 1 ? "1 row listed" : `${pieceCount} rows listed`) : "What to cut", state: stateOf(0) },
            { id: "board", label: "Board", hint: "Sheet size, margin, layout", state: stateOf(1) },
            { id: "layout", label: "Layout", hint: "Calculated in the draft", state: "todo" },
          ]}
        />
      </GlassPanel>

      {editor.offline ? (
        <Banner tone="amber" title="You are offline.">
          The plan can be created once the connection is back.
        </Banner>
      ) : null}
      {step === 1 && piecesNeedAttention ? (
        <Banner
          tone="ember"
          title="The pieces need attention before the plan can be created."
          action={
            <Button variant="secondary" size="sm" iconLeft="arrowLeft" onPress={() => setStep(0)}>
              Back to pieces
            </Button>
          }
        >
          The rows to fix are marked there.
        </Banner>
      ) : null}

      <form onSubmit={onSubmit} className="stack" noValidate>
        {step === 0 ? (
          <>
            <NameSection editor={editor} />
            <PiecesSection editor={editor} />
          </>
        ) : (
          <BoardSection editor={editor} oversizeMm={DEFAULT_OVERSIZE_MM} />
        )}

        <FormActions note={step === 0 ? "Step 1 of 2" : "Step 2 of 2 · you can change everything in the draft"}>
          {step === 0 ? (
            <ButtonLink href="/operations/cutting" variant="ghost">
              Cancel
            </ButtonLink>
          ) : (
            <Button variant="ghost" iconLeft="arrowLeft" onPress={() => setStep(0)} isDisabled={editor.pending !== null}>
              Back
            </Button>
          )}
          {step === 0 ? (
            <Button type="submit" variant="inverse" iconRight="arrowRight">
              Continue to the board
            </Button>
          ) : (
            <Button type="submit" loading={editor.pending === "save"} isDisabled={editor.offline}>
              Create cut plan
            </Button>
          )}
        </FormActions>
      </form>
    </Page>
  );
}
