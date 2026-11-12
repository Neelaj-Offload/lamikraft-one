"use client";

import type { Route } from "next";
import { useState, type MouseEvent, type ReactNode } from "react";
import { Aurora, Composer, Orb } from "./ai";
import { Avatar, AvatarGroup } from "./avatar";
import { Badge, type Tone } from "./badge";
import { Banner, type BannerTone } from "./banner";
import { Breadcrumb } from "./breadcrumb";
import { Button, ButtonLink, IconButton, IconButtonLink } from "./button";
import { Chip, ChipGroup, ChipLink } from "./chip";
import { EmptyState } from "./empty-state";
import { GlassPanel } from "./glass-panel";
import { ExternalLink, TextLink } from "./link";
import { Menu, Popover, type MenuItem } from "./menu";
import { ConfirmDialog, Drawer, Modal, ReasonDialog } from "./modal";
import { PageSummary, Pagination } from "./pagination";
import { SegmentedControl, SegmentedLinks } from "./segmented";
import { Skeleton, SkeletonRows, SkeletonText } from "./skeleton";
import { TabPanel, Tabs } from "./tabs";
import { ThemeToggle } from "./theme-toggle";
import { toast, ToastRegion } from "./toast";
import { Tooltip } from "./tooltip";

/**
 * Review page content: every core component in its main variants and states. Sample text only;
 * nothing here reads or writes data. Links point at anchors on this page so they stay in place.
 */

const here = (anchor: string) => `#${anchor}` as Route;

function Group({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="flex min-w-0 scroll-mt-6 flex-col gap-4">
      <h2 className="t-h3">{title}</h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label?: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      {label ? <p className="t-caption text-ink-3">{label}</p> : null}
      <div className="flex min-w-0 flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}

function Stack({ children }: { children: ReactNode }) {
  return (
    <GlassPanel as="div" className="flex min-w-0 flex-col gap-5">
      {children}
    </GlassPanel>
  );
}

/**
 * Link-driven controls take their selection from the URL. Here the links are page anchors, so
 * the choice is mirrored from the click instead of read from the router.
 */
function useAnchorChoice(prefix: string, initial: string) {
  const [choice, setChoice] = useState(initial);
  const onClickCapture = (event: MouseEvent<HTMLElement>) => {
    const link = event.target instanceof Element ? event.target.closest(`a[href^="#${prefix}-"]`) : null;
    const href = link?.getAttribute("href");
    if (href) setChoice(href.slice(prefix.length + 2));
  };
  return [choice, onClickCapture] as const;
}

const wait = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));

const badgeTones: Tone[] = ["neutral", "gold", "leaf", "amber", "ember", "cobalt", "inverse"];
const bannerCopy: { tone: BannerTone; title: string; text: string }[] = [
  { tone: "neutral", title: "Price list updated.", text: "New rates apply to quotations created from today." },
  { tone: "leaf", title: "Order confirmed.", text: "Production can be scheduled." },
  { tone: "amber", title: "Stock is low.", text: "Three decors are below their reorder level." },
  { tone: "ember", title: "Sync failed.", text: "Invoices were not sent to accounting." },
  { tone: "cobalt", title: "Import running.", text: "This can take a few minutes; you can keep working." },
  { tone: "gold", title: "Suggestion.", text: "Two enquiries from this customer could share one quotation." },
];

const menuItems: MenuItem[] = [
  { id: "edit", label: "Edit quotation", icon: "edit", onAction: () => toast.info("Edit chosen") },
  { id: "duplicate", label: "Duplicate", icon: "copy", description: "Starts a new draft with the same lines", onAction: () => toast.info("Duplicate chosen") },
  { id: "open", label: "Jump to overlays", icon: "arrowRight", href: here("gallery-overlays") },
  { id: "sep-1", separator: true },
  {
    id: "share",
    section: "Share",
    items: [
      { id: "print", label: "Print", icon: "printer", onAction: () => toast.info("Print chosen") },
      { id: "send", label: "Send to customer", icon: "send", isDisabled: true, description: "Approve the quotation first" },
    ],
  },
  { id: "sep-2", separator: true },
  { id: "delete", label: "Delete quotation", icon: "trash", tone: "danger", onAction: () => toast.warning("Delete chosen") },
];

export interface CoreGalleryProps {
  /** Mounts a toast region for this page. Turn off where the app shell already mounts one. */
  mountToastRegion?: boolean;
}

export function CoreGallery({ mountToastRegion = true }: CoreGalleryProps) {
  const [saving, setSaving] = useState(false);
  const [filters, setFilters] = useState({ open: true, mine: false, urgent: false });
  const [period, setPeriod] = useState("week");
  const [tab, setTab] = useState("lines");
  const [page, setPage] = useState(6);
  const [banners, setBanners] = useState(true);
  const [overlay, setOverlay] = useState<"modal" | "long" | "drawer" | "confirm" | "danger" | "reason" | null>(null);
  const [thinking, setThinking] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [status, onStatusClick] = useAnchorChoice("status", "all");
  const [view, onViewClick] = useAnchorChoice("view", "board");
  const [area, onAreaClick] = useAnchorChoice("area", "summary");
  const [linkPage, onPageClick] = useAnchorChoice("page", "2");

  const close = (open: boolean) => {
    if (!open) setOverlay(null);
  };

  return (
    <div className="flex min-w-0 flex-col gap-10">
      {mountToastRegion ? <ToastRegion /> : null}

      <Group id="gallery-surfaces" title="Glass panels">
        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <GlassPanel eyebrow="Glass" title="Default panel" action={<Badge tone="gold">New</Badge>}>
            <p className="t-body-sm text-ink-2">Frosted, for panels that sit on the ground.</p>
          </GlassPanel>
          <GlassPanel variant="strong" eyebrow="Strong" title="Over imagery">
            <p className="t-body-sm text-ink-2">More opaque, for text over busy backgrounds.</p>
          </GlassPanel>
          <GlassPanel variant="solid" eyebrow="Solid" title="Dense data">
            <p className="t-body-sm text-ink-2">No blur, for tables and long forms.</p>
          </GlassPanel>
          <GlassPanel variant="inverse" eyebrow="Inverse" title="Emphasis">
            <p className="t-body-sm">The ink panel, used once per screen at most.</p>
          </GlassPanel>
          <GlassPanel variant="outline" eyebrow="Outline" title="Quiet grouping">
            <p className="t-body-sm text-ink-2">A line only, for secondary groups.</p>
          </GlassPanel>
          <GlassPanel interactive selected eyebrow="Interactive, selected" title="Hover lifts, gold marks the choice" padding="sm">
            <p className="t-body-sm text-ink-2">Small padding uses the smaller radius.</p>
          </GlassPanel>
        </div>
      </Group>

      <Group id="gallery-buttons" title="Buttons">
        <Stack>
          <Row label="Variants">
            <Button onPress={() => toast.success("Quotation saved")}>Save quotation</Button>
            <Button variant="inverse">Create order</Button>
            <Button variant="secondary">Preview</Button>
            <Button variant="ghost">Cancel</Button>
            <Button variant="danger">Delete</Button>
          </Row>
          <Row label="Sizes and icons">
            <Button size="sm" iconLeft="plus">
              New line
            </Button>
            <Button iconLeft="download" variant="secondary">
              Export
            </Button>
            <Button size="lg" iconRight="arrowRight" variant="inverse">
              Continue
            </Button>
          </Row>
          <Row label="Loading keeps the width; disabled dims">
            <Button
              loading={saving}
              onPress={() => {
                setSaving(true);
                void wait(1600).then(() => setSaving(false));
              }}
            >
              Save changes
            </Button>
            <Button variant="inverse" loading>
              Create order
            </Button>
            <Button variant="secondary" loading>
              Preview
            </Button>
            <Button variant="danger" loading>
              Delete
            </Button>
            <Button isDisabled>Save quotation</Button>
            <Button variant="secondary" isDisabled>
              Preview
            </Button>
          </Row>
          <Row label="Links that look like buttons">
            <ButtonLink href={here("gallery-links")} iconRight="arrowRight">
              Go to links
            </ButtonLink>
            <ButtonLink href={here("gallery-chips")} variant="secondary">
              Go to chips
            </ButtonLink>
            <ButtonLink external href="https://example.com" target="_blank" variant="ghost" iconRight="external">
              External example
            </ButtonLink>
          </Row>
          <Row label="Icon buttons (the name shows as a tooltip)">
            <IconButton icon="bell" label="Notifications, 3 unread" badge />
            <IconButton icon="filter" label="Filter" variant="ghost" />
            <IconButton icon="plus" label="Add line" variant="inverse" />
            <IconButton icon="send" label="Send" variant="primary" />
            <IconButton icon="more" label="More actions" size="sm" />
            <IconButton icon="settings" label="Settings" size="lg" />
            <IconButton icon="trash" label="Delete line" variant="ghost" isDisabled />
            <IconButtonLink icon="arrowRight" label="Go to overlays" href={here("gallery-overlays")} />
          </Row>
        </Stack>
      </Group>

      <Group id="gallery-links" title="Links">
        <Stack>
          <p className="t-body text-ink-2">
            Open <TextLink href={here("gallery-tabs")}>the tabs section</TextLink> on this page, or read the{" "}
            <ExternalLink href="https://example.com">an external example</ExternalLink>.
          </p>
        </Stack>
      </Group>

      <Group id="gallery-chips" title="Chips">
        <Stack>
          <Row label="Toggles">
            <Chip selected={filters.open} onChange={(open) => setFilters((current) => ({ ...current, open }))}>
              Open
            </Chip>
            <Chip selected={filters.mine} icon="user" onChange={(mine) => setFilters((current) => ({ ...current, mine }))}>
              Assigned to me
            </Chip>
            <Chip selected={filters.urgent} tone="gold" dot onChange={(urgent) => setFilters((current) => ({ ...current, urgent }))}>
              Urgent
            </Chip>
            <Chip defaultSelected icon="tag">
              Uncontrolled
            </Chip>
            <Chip isDisabled>Unavailable</Chip>
          </Row>
          <div className="flex min-w-0 flex-col gap-2" onClickCapture={onStatusClick}>
            <p className="t-caption text-ink-3">Filters that are links (one scrolling row on phones)</p>
            <ChipGroup label="Filter by status">
              <ChipLink href={here("status-all")} selected={status === "all"} count={132}>
                All
              </ChipLink>
              <ChipLink href={here("status-draft")} selected={status === "draft"} count={18}>
                Draft
              </ChipLink>
              <ChipLink href={here("status-sent")} selected={status === "sent"} count={64}>
                Sent
              </ChipLink>
              <ChipLink href={here("status-won")} selected={status === "won"} count={41}>
                Won
              </ChipLink>
              <ChipLink href={here("status-lost")} selected={status === "lost"} count={9}>
                Lost
              </ChipLink>
            </ChipGroup>
          </div>
        </Stack>
      </Group>

      <Group id="gallery-segmented" title="Segmented controls">
        <Stack>
          <Row label="Radio group; arrow keys move the choice">
            <SegmentedControl
              label="Period"
              value={period}
              onChange={setPeriod}
              options={[
                { value: "day", label: "Day" },
                { value: "week", label: "Week" },
                { value: "month", label: "Month" },
              ]}
            />
            <SegmentedControl
              label="Density"
              size="sm"
              defaultValue="comfortable"
              options={[
                { value: "comfortable", label: "Comfortable" },
                { value: "compact", label: "Compact" },
              ]}
            />
            <SegmentedControl
              label="Currency"
              glass
              options={[
                { value: "inr", label: "INR" },
                { value: "usd", label: "USD" },
                { value: "eur", label: "EUR" },
              ]}
            />
            <SegmentedControl
              label="Unavailable"
              isDisabled
              options={[
                { value: "a", label: "Sheets" },
                { value: "b", label: "Square metres" },
              ]}
            />
          </Row>
          <div className="flex min-w-0 flex-col gap-2" onClickCapture={onViewClick}>
            <p className="t-caption text-ink-3">The same control as links</p>
            <div>
              <SegmentedLinks
                label="View"
                value={view}
                options={[
                  { value: "board", label: "Board", href: here("view-board") },
                  { value: "list", label: "List", href: here("view-list") },
                  { value: "calendar", label: "Calendar", href: here("view-calendar") },
                ]}
              />
            </div>
          </div>
        </Stack>
      </Group>

      <Group id="gallery-tabs" title="Tabs">
        <Stack>
          <Tabs
            label="Quotation sections"
            selectedKey={tab}
            onSelectionChange={setTab}
            tabs={[
              { id: "lines", label: "Lines", count: 12 },
              { id: "pricing", label: "Pricing" },
              { id: "documents", label: "Documents", count: 3 },
              { id: "history", label: "History" },
              { id: "messages", label: "Customer messages", count: 1284 },
            ]}
          >
            <TabPanel id="lines">
              <p className="t-body-sm text-ink-2">Twelve lines. In-page panels: arrow keys move between tabs.</p>
            </TabPanel>
            <TabPanel id="pricing">
              <p className="t-body-sm text-ink-2">Pricing panel.</p>
            </TabPanel>
            <TabPanel id="documents">
              <p className="t-body-sm text-ink-2">Three documents.</p>
            </TabPanel>
            <TabPanel id="history">
              <p className="t-body-sm text-ink-2">History panel.</p>
            </TabPanel>
            <TabPanel id="messages">
              <p className="t-body-sm text-ink-2">Customer messages panel.</p>
            </TabPanel>
          </Tabs>
          <Tabs
            label="Stock views"
            variant="pills"
            defaultSelectedKey="reserved"
            tabs={[
              { id: "available", label: "Available", count: 240 },
              { id: "reserved", label: "Reserved", count: 36 },
              { id: "transit", label: "In transit" },
            ]}
          >
            <TabPanel id="available">
              <p className="t-body-sm text-ink-2">Available stock.</p>
            </TabPanel>
            <TabPanel id="reserved">
              <p className="t-body-sm text-ink-2">Reserved stock.</p>
            </TabPanel>
            <TabPanel id="transit">
              <p className="t-body-sm text-ink-2">Stock in transit.</p>
            </TabPanel>
          </Tabs>
          <div className="min-w-0" onClickCapture={onAreaClick}>
            <Tabs
              label="Customer areas"
              selectedKey={area}
              tabs={[
                { id: "summary", label: "Summary", href: here("area-summary") },
                { id: "orders", label: "Orders", count: 27, href: here("area-orders") },
                { id: "contacts", label: "Contacts", href: here("area-contacts") },
              ]}
            >
              <p className="t-body-sm text-ink-2">Tabs that are links: the route renders the content ({area}).</p>
            </Tabs>
          </div>
        </Stack>
      </Group>

      <Group id="gallery-navigation" title="Breadcrumb and pagination">
        <Stack>
          <Row label="Collapses to a back link on phones">
            <Breadcrumb
              items={[
                { label: "Sales", href: here("gallery-surfaces") },
                { label: "Quotations", href: here("gallery-buttons") },
                { label: "LK-QT-2026-0041" },
              ]}
            />
          </Row>
          <Row label="Buttons (state held by the screen)">
            <Pagination page={page} pages={20} onChange={setPage} />
            <PageSummary from={(page - 1) * 25 + 1} to={Math.min(page * 25, 482)} total={482} noun="quotations" />
          </Row>
          <div className="flex min-w-0 flex-col gap-2" onClickCapture={onPageClick}>
            <p className="t-caption text-ink-3">Links (each page is a URL)</p>
            <div className="flex min-w-0 flex-wrap items-center gap-3">
              <Pagination label="Orders pages" page={Number(linkPage)} pages={5} hrefFor={(target) => here(`page-${target}`)} />
              <PageSummary from={(Number(linkPage) - 1) * 25 + 1} to={Math.min(Number(linkPage) * 25, 118)} total={118} noun="orders" />
            </div>
          </div>
        </Stack>
      </Group>

      <Group id="gallery-badges" title="Badges and avatars">
        <Stack>
          <Row label="Tones">
            {badgeTones.map((tone) => (
              <Badge key={tone} tone={tone}>
                {tone}
              </Badge>
            ))}
          </Row>
          <Row label="Dot, icon, small, outline">
            <Badge tone="leaf" dot>
              Approved
            </Badge>
            <Badge tone="amber" icon="clock">
              Awaiting approval
            </Badge>
            <Badge tone="ember" icon="alert">
              Overdue
            </Badge>
            <Badge tone="cobalt" size="sm">
              Draft
            </Badge>
            <Badge outline>Export</Badge>
            <Badge tone="gold" size="sm" dot>
              Priority
            </Badge>
          </Row>
          <Row label="Avatars">
            <Avatar name="Meera Nair" size="sm" />
            <Avatar name="Sahil Kapoor" status="online" />
            <Avatar name="Neha Rao" size="lg" status="away" />
            <Avatar name="Ravi Menon" size="xl" status="off" />
            <AvatarGroup
              people={[{ name: "Kabir Shah" }, { name: "Arjun Das" }, { name: "Ananya Iyer" }, { name: "Priya Sen" }, { name: "Meera Nair" }, { name: "Neha Rao" }]}
              max={4}
            />
          </Row>
        </Stack>
      </Group>

      <Group id="gallery-banners" title="Banners">
        <div className="flex min-w-0 flex-col gap-3">
          {banners ? (
            bannerCopy.map((banner, index) => (
              <Banner
                key={banner.tone}
                tone={banner.tone}
                title={banner.title}
                action={
                  index === 3 ? (
                    <Button size="sm" variant="secondary" onPress={() => toast.info("Retry chosen")}>
                      Retry
                    </Button>
                  ) : undefined
                }
                onClose={index === 0 || index === 3 ? () => setBanners(false) : undefined}
              >
                {banner.text}
              </Banner>
            ))
          ) : (
            <Row>
              <Button variant="secondary" onPress={() => setBanners(true)}>
                Show the banners again
              </Button>
            </Row>
          )}
        </div>
      </Group>

      <Group id="gallery-toasts" title="Toasts and tooltips">
        <Stack>
          <Row label="One of each tone (success and info leave after six seconds)">
            <Button
              variant="secondary"
              onPress={() =>
                toast.success("Quotation sent", {
                  description: "LK-QT-2026-0041 went to the customer.",
                  action: { label: "View", href: here("gallery-toasts") },
                })
              }
            >
              Success
            </Button>
            <Button variant="secondary" onPress={() => toast.info("Prices refreshed", { description: "Today's exchange rates are applied." })}>
              Info
            </Button>
            <Button variant="secondary" onPress={() => toast.warning("Stock is low", { description: "Three decors are below their reorder level." })}>
              Warning
            </Button>
            <Button variant="secondary" onPress={() => toast.error("Order not created", { description: "The quotation has no approved price." })}>
              Error
            </Button>
          </Row>
          <Row label="Tooltips (hover for half a second, or focus)">
            <Tooltip text="Search everything" shortcut="/">
              <Button variant="secondary" iconLeft="search">
                Search
              </Button>
            </Tooltip>
            <Tooltip text="Opens below when there is no room above" placement="bottom">
              <Button variant="ghost">Below</Button>
            </Tooltip>
            <Tooltip text="Links take a tooltip too" focusable>
              <ButtonLink href={here("gallery-links")} variant="ghost">
                A link with a hint
              </ButtonLink>
            </Tooltip>
          </Row>
        </Stack>
      </Group>

      <Group id="gallery-overlays" title="Modal, drawer, dialogs, menu and popover">
        <Stack>
          <Row label="Overlays (a modal is a bottom sheet on phones)">
            <Button variant="secondary" onPress={() => setOverlay("modal")}>
              Open modal
            </Button>
            <Button variant="secondary" onPress={() => setOverlay("long")}>
              Open long modal
            </Button>
            <Button variant="secondary" onPress={() => setOverlay("drawer")}>
              Open drawer
            </Button>
            <Button variant="secondary" onPress={() => setOverlay("confirm")}>
              Confirm
            </Button>
            <Button variant="secondary" onPress={() => setOverlay("danger")}>
              Confirm deletion
            </Button>
            <Button variant="secondary" onPress={() => setOverlay("reason")}>
              Ask for a reason
            </Button>
          </Row>
          <Row label="Menu and popover">
            <Menu label="Quotation actions" items={menuItems} trigger={<Button variant="secondary" iconRight="chevronDown">Actions</Button>} />
            <Menu label="More actions" items={menuItems} placement="bottom start" trigger={<IconButton icon="more" label="More actions" />} />
            <Popover label="About margins" trigger={<Button variant="ghost" iconLeft="info">What is margin</Button>}>
              {(dismiss) => (
                <div className="flex max-w-64 flex-col items-start gap-3">
                  <p className="t-body-sm text-ink-2">Margin is the selling price less landed cost, as a share of the selling price.</p>
                  <Button size="sm" variant="secondary" onPress={dismiss}>
                    Got it
                  </Button>
                </div>
              )}
            </Popover>
          </Row>
        </Stack>

        <Modal
          isOpen={overlay === "modal"}
          onOpenChange={close}
          title="Send the quotation"
          description="The customer gets a link that stays valid for 30 days."
          actions={
            <>
              <Button variant="ghost" onPress={() => setOverlay(null)}>
                Not now
              </Button>
              <Button
                onPress={() => {
                  setOverlay(null);
                  toast.success("Quotation sent");
                }}
              >
                Send quotation
              </Button>
            </>
          }
        >
          <p>LK-QT-2026-0041 for Crown Decor (Demo), 12 lines.</p>
        </Modal>

        <Modal
          isOpen={overlay === "long"}
          onOpenChange={close}
          size="lg"
          title="Terms of sale"
          actions={
            <Button variant="inverse" onPress={() => setOverlay(null)}>
              Close terms
            </Button>
          }
        >
          <div className="flex flex-col gap-3">
            {Array.from({ length: 14 }, (_, index) => (
              <p key={index}>
                {index + 1}. Sample clause. The body scrolls while the title and the action row stay where they are, so the way out is
                always in view.
              </p>
            ))}
          </div>
        </Modal>

        <Drawer
          isOpen={overlay === "drawer"}
          onOpenChange={close}
          title="Line 4"
          description="Walnut Crown, 1 mm, suede finish"
          footer={
            <>
              <Button variant="ghost" onPress={() => setOverlay(null)}>
                Discard
              </Button>
              <Button
                onPress={() => {
                  setOverlay(null);
                  toast.success("Line saved");
                }}
              >
                Save line
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-4">
            <SkeletonText lines={4} />
            <p className="t-body-sm text-ink-2">A side sheet on desktop and a full-height sheet on phones. The body scrolls; the footer stays.</p>
            <SkeletonRows rows={6} columns={3} />
          </div>
        </Drawer>

        <ConfirmDialog
          isOpen={overlay === "confirm"}
          onOpenChange={close}
          title="Approve this quotation"
          description="The price is locked and the customer can be sent the quotation."
          confirmLabel="Approve quotation"
          onConfirm={() => wait(900).then(() => void toast.success("Quotation approved"))}
        />

        <ConfirmDialog
          isOpen={overlay === "danger"}
          onOpenChange={close}
          tone="danger"
          title="Delete this draft"
          description="The draft and its 12 lines are removed. This cannot be undone."
          confirmLabel="Delete draft"
          onConfirm={() => wait(900).then(() => void toast.success("Draft deleted"))}
        />

        <ReasonDialog
          isOpen={overlay === "reason"}
          onOpenChange={close}
          tone="danger"
          title="Reject the discount"
          description="The salesperson is told, with your reason."
          confirmLabel="Reject discount"
          reasonLabel="Reason for rejecting"
          reasonHelp="Shown to the salesperson and kept in the history."
          onConfirm={(reason) => wait(900).then(() => void toast.success("Discount rejected", { description: reason }))}
        />
      </Group>

      <Group id="gallery-loading" title="Skeletons and empty states">
        <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
          <GlassPanel className="flex min-w-0 flex-col gap-4">
            <div className="flex items-center gap-3">
              <Skeleton circle width={40} height={40} />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton width="50%" height={14} />
                <Skeleton width="30%" />
              </div>
            </div>
            <SkeletonText lines={3} />
          </GlassPanel>
          <GlassPanel padding="none" className="min-w-0">
            <SkeletonRows rows={4} columns={4} />
          </GlassPanel>
          <GlassPanel className="min-w-0">
            <EmptyState
              icon="fileText"
              title="No quotations yet"
              text="Create the first one from an enquiry, or start from a blank quotation."
              actions={
                <>
                  <Button iconLeft="plus" onPress={() => toast.info("New quotation chosen")}>
                    New quotation
                  </Button>
                  <ButtonLink variant="ghost" href={here("gallery-buttons")}>
                    See enquiries
                  </ButtonLink>
                </>
              }
            />
          </GlassPanel>
          <GlassPanel className="min-w-0">
            <EmptyState compact icon="search" title="Nothing matches" text="Try fewer filters or a different word." />
          </GlassPanel>
        </div>
      </Group>

      <Group id="gallery-assistant" title="Assistant: orb, aurora and composer">
        <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-2">
          <GlassPanel className="relative flex min-h-56 min-w-0 flex-wrap items-center justify-around gap-6 overflow-hidden">
            <Aurora quiet />
            <Orb size="sm" />
            <Orb state="thinking" />
            <Orb size="lg" state="listening" />
          </GlassPanel>
          <div className="flex min-w-0 flex-col gap-3">
            <Composer
              label="Message to the assistant"
              busy={thinking}
              suggestions={["Which quotations expire this week", "Draft a reply to Crown Decor"]}
              onSend={(text) => {
                setSent(text);
                setThinking(true);
                void wait(1800).then(() => setThinking(false));
              }}
            />
            <p className="t-caption text-ink-3" role="status">
              {thinking ? "Thinking…" : sent ? `Last message: ${sent}` : "Enter sends; Shift and Enter starts a new line."}
            </p>
            <Composer label="Message (unavailable)" placeholder="The assistant is switched off for this workspace" disabled />
          </div>
        </div>
      </Group>

      <Group id="gallery-theme" title="Theme">
        <Stack>
          <Row label="Applies at once; saved to the profile when signed in">
            <ThemeToggle />
            <ThemeToggle size="sm" />
            <ThemeToggle variant="icon" />
          </Row>
        </Stack>
      </Group>
    </div>
  );
}
