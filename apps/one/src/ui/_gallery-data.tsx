"use client";

import type { Route } from "next";
import { useState, type ReactNode } from "react";
import { compareDecimalStr } from "@/lib/format/decimal";
import { Badge, type Tone } from "~/ui/badge";
import { Button } from "~/ui/button";
import { EmptyState } from "~/ui/empty-state";
import { BarChart, LineChart, ProgressBar, ProgressRing, Sparkline } from "./charts";
import { Checkbox, CheckboxGroup, RadioCards, RadioGroup, Slider, Switch } from "./choice";
import { CountUp } from "./count-up";
import { DataTable, MediaCell, TableFooter, type Column, type SortState } from "./data-table";
import { DatePicker, DateRangePicker, type DateRange } from "./date-picker";
import { FormActions, FormSection } from "./field";
import { FileField } from "./file-field";
import { Code, Dash, DateText, Money, Qty } from "./format";
import { FactStrip, KeyValue } from "./key-value";
import { DecimalField, IntegerField } from "./number-field";
import { Schedule } from "./schedule";
import { SearchField } from "./search-field";
import { ComboBox, Select } from "./select";
import { StatRow, StatTile } from "./stat-tile";
import { Textarea, TextField } from "./text-field";
import { Timeline } from "./timeline";

/* Review page content for the input and data components: every component in its main variants and
   states, on demo data from the Crown Decor (Demo) world. Mounted by the review route. */

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="t-h3 m-0">{title}</h2>
      {children}
    </section>
  );
}

/** Local state for a demo control, so every example on the page can be operated. */
function Stateful<Value>({
  initial,
  children,
}: {
  initial: Value;
  children: (value: Value, set: (value: Value) => void) => ReactNode;
}) {
  const [value, set] = useState(initial);
  return <>{children(value, set)}</>;
}

function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={`lk-glass lk-glass-pad-md ${className ?? ""}`}>{children}</div>;
}

const fieldGrid = "grid grid-cols-1 items-start gap-5 md:grid-cols-2 xl:grid-cols-3";

const PAYMENT_TERMS = [
  { value: "advance", label: "100% advance", description: "Before production starts" },
  { value: "30-70", label: "30% advance, 70% before dispatch", icon: "banknote" as const },
  { value: "lc", label: "Letter of credit at sight", description: "Confirmed, irrevocable" },
  { value: "net30", label: "Net 30 days", description: "Approved customers only", isDisabled: true },
];

const CUSTOMERS = [
  { id: "c1", label: "Nordhaus Interiors GmbH", description: "Hamburg, Germany" },
  { id: "c2", label: "Atelier Dumont SARL", description: "Lyon, France" },
  { id: "c3", label: "Harbour & Finch Ltd", description: "Bristol, United Kingdom" },
  { id: "c4", label: "Casa Verano S.L.", description: "Valencia, Spain" },
  { id: "c5", label: "Lakeshore Millwork Inc.", description: "Chicago, United States" },
];

interface QuoteRow {
  id: string;
  number: string;
  customer: string;
  country: string;
  owner: string;
  status: { text: string; tone: Tone };
  sheets: string;
  amount: { amount: string; currency: string };
  validUntil: string;
}

const QUOTES: QuoteRow[] = [
  { id: "q41", number: "LK-QT-2026-0041", customer: "Nordhaus Interiors GmbH", country: "Germany", owner: "Meera", status: { text: "Sent", tone: "cobalt" }, sheets: "2400", amount: { amount: "57600.00", currency: "EUR" }, validUntil: "2026-10-26" },
  { id: "q40", number: "LK-QT-2026-0040", customer: "Atelier Dumont SARL", country: "France", owner: "Neha", status: { text: "Accepted", tone: "leaf" }, sheets: "960", amount: { amount: "21312.00", currency: "EUR" }, validUntil: "2026-10-20" },
  { id: "q39", number: "LK-QT-2026-0039", customer: "Harbour & Finch Ltd", country: "United Kingdom", owner: "Meera", status: { text: "Needs approval", tone: "amber" }, sheets: "5200", amount: { amount: "98540.00", currency: "GBP" }, validUntil: "2026-10-18" },
  { id: "q38", number: "LK-QT-2026-0038", customer: "Casa Verano S.L.", country: "Spain", owner: "Ravi", status: { text: "Draft", tone: "neutral" }, sheets: "320", amount: { amount: "7424.00", currency: "EUR" }, validUntil: "2026-11-02" },
  { id: "q37", number: "LK-QT-2026-0037", customer: "Lakeshore Millwork Inc.", country: "United States", owner: "Kabir", status: { text: "Expired", tone: "ember" }, sheets: "1800", amount: { amount: "46260.00", currency: "USD" }, validUntil: "2026-10-05" },
  { id: "q36", number: "LK-QT-2026-0036", customer: "Nordhaus Interiors GmbH", country: "Germany", owner: "Neha", status: { text: "Accepted", tone: "leaf" }, sheets: "3600", amount: { amount: "84960.00", currency: "EUR" }, validUntil: "2026-10-09" },
  { id: "q35", number: "LK-QT-2026-0035", customer: "Studio Østergaard & Partners Arkitekter ApS, Copenhagen office", country: "Denmark", owner: "Ananya", status: { text: "Sent", tone: "cobalt" }, sheets: "12500", amount: { amount: "301250.00", currency: "EUR" }, validUntil: "2026-10-30" },
  { id: "q34", number: "LK-QT-2026-0034", customer: "Atelier Dumont SARL", country: "France", owner: "Priya", status: { text: "Draft", tone: "neutral" }, sheets: "80", amount: { amount: "1984.00", currency: "EUR" }, validUntil: "2026-11-06" },
];

function sortQuotes(rows: QuoteRow[], sort: SortState): QuoteRow[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  const pick = (row: QuoteRow) =>
    sort.key === "customer" ? row.customer : sort.key === "validUntil" ? row.validUntil : row.number;
  return [...rows].sort((a, b) => {
    // Decimal strings are compared digit by digit; they are never turned into floats.
    if (sort.key === "amount") return sign * compareDecimalStr(a.amount.amount, b.amount.amount);
    if (sort.key === "sheets") return sign * compareDecimalStr(a.sheets, b.sheets);
    return sign * pick(a).localeCompare(pick(b));
  });
}

const QUOTE_COLUMNS: Column<QuoteRow>[] = [
  {
    key: "number",
    header: "Quotation",
    primary: true,
    sortable: true,
    cell: (row) => <MediaCell icon="fileText" title={<Code>{row.number}</Code>} subtitle={`Owner: ${row.owner}`} />,
  },
  { key: "customer", header: "Customer", sortable: true, cell: (row) => row.customer },
  { key: "country", header: "Country", hideOnMobile: true, cell: (row) => row.country },
  {
    key: "status",
    header: "Status",
    cell: (row) => (
      <Badge tone={row.status.tone} dot>
        {row.status.text}
      </Badge>
    ),
  },
  {
    key: "sheets",
    header: "Sheets",
    numeric: true,
    sortable: true,
    cell: (row) => <Qty value={{ value: row.sheets, uom: "sheets" }} />,
  },
  { key: "amount", header: "Amount", numeric: true, sortable: true, cell: (row) => <Money value={row.amount} /> },
  {
    key: "validUntil",
    header: "Valid until",
    mobileLabel: "Valid until",
    sortable: true,
    cell: (row) => <DateText value={row.validUntil} style="business" />,
  },
];

const WEEKS = ["W33", "W34", "W35", "W36", "W37", "W38", "W39", "W40"];

export function DataGallery() {
  const [company, setCompany] = useState("Nordhaus Interiors GmbH");
  const [price, setPrice] = useState("24.50");
  const [quantity, setQuantity] = useState("2400");
  const [copies, setCopies] = useState<number | null>(2);
  const [query, setQuery] = useState("");
  const [terms, setTerms] = useState<string | null>("30-70");
  const [customerText, setCustomerText] = useState("");
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [incoterm, setIncoterm] = useState("fob");
  const [finish, setFinish] = useState("matte");
  const [notify, setNotify] = useState(true);
  const [margin, setMargin] = useState(18);
  const [validUntil, setValidUntil] = useState<string | null>("2026-10-26");
  const [period, setPeriod] = useState<DateRange | null>({ start: "2026-10-01", end: "2026-10-12" });
  const [sort, setSort] = useState<SortState>({ key: "number", dir: "desc" });
  const [openOrders, setOpenOrders] = useState(128);

  const matches = CUSTOMERS.filter((customer) =>
    customer.label.toLowerCase().includes(customerText.trim().toLowerCase()),
  );
  const rows = sortQuotes(QUOTES, sort);
  const toggleSort = (key: string) =>
    setSort((current) => ({ key, dir: current.key === key && current.dir === "asc" ? "desc" : "asc" }));

  return (
    <div className="flex flex-col gap-10">
      <Group title="Text fields">
        <Panel className={fieldGrid}>
          <TextField label="Company name" value={company} onChange={setCompany} autoComplete="organization" isRequired />
          <TextField label="Contact email" type="email" iconLeft="mail" placeholder="name@company.com" optional help="Quotations are sent to this address." />
          <TextField label="Website" prefix="https://" defaultValue="nordhaus-interiors.example" suffix=".de" />
          <TextField
            label="GST number"
            defaultValue="27ABCDE1234"
            maxLength={15}
            error="This GST number is 11 characters. Enter all 15, for example 27ABCDE1234F1Z5."
          />
          <TextField label="Customer code" defaultValue="CUS-000184" isDisabled />
          <TextField label="Created by" defaultValue="Meera" isReadOnly help="Set when the record was created." />
          <TextField label="Dense" size="sm" placeholder="32px control" />
          <TextField label="Large, on glass" size="lg" glass iconLeft="search" placeholder="48px control" />
          <TextField label="Hidden label" hideLabel placeholder="Label kept for screen readers" />
          <Textarea
            className="md:col-span-2"
            label="Notes for the customer"
            defaultValue={"Prices are FOB Mundra and hold for 14 days.\nSamples of the three decors ship separately this week."}
            help="Grows as you type, up to 12 rows."
          />
          <Textarea label="Reason for discount" rows={2} error="A reason is needed for discounts above 5%. Say why this customer gets it." />
        </Panel>
      </Group>

      <Group title="Number fields">
        <Panel className={fieldGrid}>
          <DecimalField label="Unit price" value={price} onChange={setPrice} prefix="EUR" suffix="per sheet" help={`Stored as "${price}"`} />
          <DecimalField label="Quantity" value={quantity} onChange={setQuantity} maxFractionDigits={0} suffix="sheets" isRequired />
          <Stateful initial="-150.00">
            {(value, set) => <DecimalField label="Adjustment" value={value} onChange={set} allowNegative prefix="EUR" maxFractionDigits={2} />}
          </Stateful>
          <Stateful initial="0.8">
            {(value, set) => (
              <DecimalField label="Thickness" value={value} onChange={set} suffix="mm" error="0.8 mm is not made in this decor. Choose 0.7 or 1.0." />
            )}
          </Stateful>
          <DecimalField label="Exchange rate" value="89.4200" onChange={() => undefined} isDisabled />
          <IntegerField label="Copies to print" value={copies} onChange={setCopies} minValue={1} maxValue={20} help="Between 1 and 20." />
          <IntegerField label="Lead time, days" value={21} onChange={() => undefined} isDisabled />
        </Panel>
      </Group>

      <Group title="Search">
        <Panel className={fieldGrid}>
          <SearchField label="Search quotations" value={query} onChange={setQuery} placeholder="Search quotations" shortcut="/" />
          <SearchField label="Search customers" defaultValue="Nordhaus" isPending glass={false} />
          <SearchField label="Search stock" size="sm" placeholder="Dense" />
        </Panel>
      </Group>

      <Group title="Select and combo box">
        <Panel className={fieldGrid}>
          <Select label="Payment terms" options={PAYMENT_TERMS} value={terms} onChange={setTerms} />
          <Select label="Currency" placeholder="Choose a currency" options={[{ value: "EUR", label: "Euro" }, { value: "USD", label: "US dollar" }, { value: "GBP", label: "Pound sterling" }, { value: "INR", label: "Indian rupee" }]} isRequired />
          <Select label="Price list" options={PAYMENT_TERMS} error="Choose a price list before adding lines." />
          <Select label="Branch" options={[{ value: "mum", label: "Mumbai" }]} defaultValue="mum" isDisabled />
          <ComboBox
            label="Customer"
            items={matches}
            inputValue={customerText}
            onInputChange={setCustomerText}
            selectedKey={customerId}
            onSelectionChange={setCustomerId}
            placeholder="Search by name"
            help="Type a few letters of the company name."
          />
          <Stateful initial="walnut">
            {(text, setText) => (
              <ComboBox label="Product, loading" items={[]} inputValue={text} onInputChange={setText} selectedKey={null} onSelectionChange={() => undefined} isLoading />
            )}
          </Stateful>
          <Stateful initial="zebrano 9mm">
            {(text, setText) => (
              <ComboBox label="Product, no matches" items={[]} inputValue={text} onInputChange={setText} selectedKey={null} onSelectionChange={() => undefined} />
            )}
          </Stateful>
        </Panel>
      </Group>

      <Group title="Choices">
        <Panel className={fieldGrid}>
          <div className="flex flex-col items-start gap-3">
            <Checkbox label="Include packing list" defaultSelected />
            <Checkbox label="Send a copy to me" description="To the email on your profile." />
            <Checkbox label="All lines selected" isIndeterminate />
            <Checkbox label="Export documents ready" isDisabled defaultSelected />
          </div>
          <CheckboxGroup
            label="Documents to attach"
            defaultValue={["quote"]}
            options={[
              { value: "quote", label: "Quotation PDF" },
              { value: "spec", label: "Technical data sheet" },
              { value: "cert", label: "Test certificates", description: "EN 438 and fire rating" },
            ]}
            help="Attached to the email in this order."
          />
          <RadioGroup
            label="Incoterm"
            value={incoterm}
            onChange={setIncoterm}
            options={[
              { value: "exw", label: "EXW", description: "Buyer collects from the factory" },
              { value: "fob", label: "FOB", description: "Loaded on the vessel at Mundra" },
              { value: "cif", label: "CIF", description: "Freight and insurance included" },
            ]}
          />
          <RadioGroup
            label="Sheet size"
            orientation="horizontal"
            defaultValue="8x4"
            options={[{ value: "8x4", label: "8 × 4 ft" }, { value: "10x4", label: "10 × 4 ft" }, { value: "12x5", label: "12 × 5 ft" }]}
            error="12 × 5 ft is out of stock in this decor. Choose another size."
          />
          <div className="flex flex-col items-start gap-3">
            <Switch label="Notify the customer" isSelected={notify} onChange={setNotify} />
            <Switch label="Lock prices" description="Lines cannot be repriced after approval." tone="inverse" defaultSelected />
            <Switch label="Auto-reorder" isDisabled />
          </div>
          <Slider label="Target margin" min={0} max={40} value={margin} onChange={setMargin} format={(value) => `${value}%`} />
          <RadioCards
            className="md:col-span-2 xl:col-span-3"
            label="Surface finish"
            value={finish}
            onChange={setFinish}
            options={[
              { value: "matte", label: "Suede matte", description: "Low sheen, hides fingerprints. The default for cabinetry.", icon: "layers" },
              { value: "gloss", label: "High gloss", description: "Mirror finish with a protective film. Adds 4 days.", icon: "sparkles" },
              { value: "texture", label: "Synchro texture", description: "Embossed in register with the grain.", icon: "swatch" },
            ]}
          />
        </Panel>
      </Group>

      <Group title="Dates and files">
        <Panel className={fieldGrid}>
          <DatePicker label="Valid until" value={validUntil} onChange={setValidUntil} minValue="2026-10-12" help="At least today." />
          <DateRangePicker label="Reporting period" value={period} onChange={setPeriod} />
          <Stateful<string | null> initial="2026-10-08">
            {(value, set) => (
              <DatePicker label="Dispatch date" value={value} onChange={set} error="This date has passed. Choose 12 Oct 2026 or later." />
            )}
          </Stateful>
          <DatePicker label="Invoice date" value="2026-10-12" onChange={() => undefined} isDisabled />
          <FileField
            className="md:col-span-2"
            label="Purchase order"
            accept={[".pdf", "image/*"]}
            multiple
            maxBytes={10 * 1024 * 1024}
            onSelect={() => undefined}
            help="The signed order from the customer."
          />
          <FileField label="Price list import" accept={[".xlsx"]} onSelect={() => undefined} error="The last upload had no price column. Add a column named Price and upload it again." />
          <FileField label="Decor swatch" onSelect={() => undefined} isDisabled />
        </Panel>
      </Group>

      <Group title="Form layout">
        <FormSection title="Commercial terms" description="These apply to every line unless a line overrides them.">
          <Select label="Payment terms" options={PAYMENT_TERMS} defaultValue="30-70" />
          <DatePicker label="Valid until" value={validUntil} onChange={setValidUntil} />
          <Stateful initial="1250.00">
            {(value, set) => <DecimalField label="Freight" value={value} onChange={set} prefix="EUR" maxFractionDigits={2} />}
          </Stateful>
          <TextField label="Port of loading" defaultValue="Mundra" optional />
          <Textarea className="col-span-full" label="Terms shown on the quotation" rows={2} defaultValue="Prices hold for 14 days from the date of this quotation." />
        </FormSection>
        <FormActions note="Unsaved changes">
          <Button variant="ghost">Discard</Button>
          <Button variant="secondary">Save draft</Button>
          <Button iconLeft="send">Send for approval</Button>
        </FormActions>
      </Group>

      <Group title="Stat tiles">
        <StatRow>
          <Panel>
            <StatTile
              label="Open orders"
              value={<CountUp value={openOrders} />}
              delta={12}
              deltaLabel="vs last week"
              data={[84, 92, 88, 101, 97, 110, 121, 128]}
            />
          </Panel>
          <Panel>
            <StatTile label="Quoted this month" value={<Money value={{ amount: "418250.00", currency: "EUR" }} compact />} delta={-4} foot="vs September" data={[52, 61, 58, 49, 47, 44, 46, 42]} />
          </Panel>
          <Panel>
            <StatTile label="On-time dispatch" value="94%" trend="flat" delta="0 pts" dot bar={94} />
          </Panel>
          <Panel>
            <StatTile label="Enquiries waiting" value="7" foot="Oldest: 2 days" dot="var(--chart-3)" href={"/" as Route} />
          </Panel>
          <div className="lk-glass lk-glass-inverse lk-glass-pad-md">
            <StatTile label="Stock value" value={<Money value={{ amount: "12400000.00", currency: "INR" }} compact />} size="xl" inverse delta={3} deltaLabel="this quarter" />
          </div>
        </StatRow>
        <div>
          <Button variant="secondary" size="sm" iconLeft="refresh" onPress={() => setOpenOrders((count) => (count === 128 ? 143 : 128))}>
            Change open orders
          </Button>
        </div>
      </Group>

      <Group title="Charts">
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Panel>
            <LineChart
              label="Quotations sent and accepted per week"
              series={[
                { name: "Sent", data: [18, 22, 19, 27, 24, 31, 29, 36] },
                { name: "Accepted", data: [7, 9, 8, 12, 11, 13, 15, 17] },
                { name: "Target", data: [20, 21, 22, 23, 24, 25, 26, 27], dashed: true, color: "var(--chart-6)" },
              ]}
              labels={WEEKS}
              callout
              legend
            />
          </Panel>
          <Panel>
            <BarChart label="Sheets dispatched per day, this week" data={[1240, 1680, 950, 2140, 1820, 760]} labels={["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]} highlight={3} />
          </Panel>
          <Panel className="flex flex-wrap items-center gap-6">
            <ProgressRing value={68} label="Order LK-SO-2026-0112 packed" caption="Packed" />
            <ProgressRing value={100} label="Samples dispatched" tone="leaf" size={72} stroke={6} />
            <ProgressRing value={32} label="Credit limit used" tone="ink" size={72} stroke={6} />
            <Sparkline data={[4, 6, 5, 9, 8, 12, 11, 15]} label="Enquiries, last 8 weeks" />
            <Sparkline data={[15, 12, 13, 9, 10, 7, 6, 4]} label="Returns, last 8 weeks" color="var(--chart-2)" area={false} />
          </Panel>
          <Panel className="flex flex-col gap-4">
            <ProgressBar value={66} label="Production" detail="8 of 12 rolls" />
            <ProgressBar value={92} label="Credit limit used" tone="ember" thick />
            <ProgressBar value={100} label="Documents" tone="leaf" detail="Complete" />
            <ProgressBar value={60} label="Approval steps" segments={5} detail="3 of 5" />
          </Panel>
        </div>
      </Group>

      <Group title="Data table">
        <Panel className="lk-glass-pad-none">
          <DataTable
            label="Quotations"
            columns={QUOTE_COLUMNS}
            rows={rows}
            rowKey={(row) => row.id}
            rowHref={() => "/" as Route}
            sort={sort}
            onSort={toggleSort}
            selectedKey="q39"
            footer={<TableFooter left="Showing 8 of 312" right="Sorted in the browser for this demo" />}
          />
        </Panel>
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Panel className="lk-glass-pad-none">
            <DataTable label="Quotations, loading" columns={QUOTE_COLUMNS.slice(0, 4)} rows={[]} rowKey={(row) => row.id} loading skeletonRows={4} />
          </Panel>
          <Panel className="lk-glass-pad-none">
            <DataTable
              label="Quotations, none"
              columns={QUOTE_COLUMNS}
              rows={[]}
              rowKey={(row) => row.id}
              empty={
                <EmptyState
                  compact
                  icon="fileText"
                  title="No quotations match"
                  text="Nothing fits these filters. Clear them, or start a new quotation."
                  actions={<Button size="sm" variant="secondary">Clear filters</Button>}
                />
              }
            />
          </Panel>
        </div>
        <Panel className="lk-glass-pad-none">
          <DataTable
            label="Quotations, dense with a fixed height"
            columns={QUOTE_COLUMNS}
            rows={rows}
            rowKey={(row) => row.id}
            onRowAction={() => undefined}
            dense
            mobile="scroll"
            maxHeight="260px"
          />
        </Panel>
      </Group>

      <Group title="Key value and facts">
        <Panel>
          <FactStrip
            items={[
              { label: "Customer", value: "Nordhaus Interiors GmbH", icon: "building" },
              { label: "Amount", value: <Money value={{ amount: "57600.00", currency: "EUR" }} />, icon: "banknote" },
              { label: "Valid until", value: <DateText value="2026-10-26" />, icon: "calendar" },
              { label: "Owner", value: "Meera", icon: "user" },
              { label: "Approved by", value: null, icon: "badgeCheck" },
            ]}
          />
        </Panel>
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <Panel>
            <KeyValue
              columns={2}
              items={[
                { label: "Decor", value: "Smoked walnut" },
                { label: "SKU", value: "LK-DEC-4471-SM", mono: true },
                { label: "Thickness", value: <Qty value={{ value: "1.0", uom: "mm" }} /> },
                { label: "Finish", value: "Suede matte" },
                { label: "Core", value: "" },
                { label: "Last counted", value: <DateText value="2026-10-11T11:42:00Z" style="dayTime" /> },
              ]}
            />
          </Panel>
          <Panel>
            <KeyValue
              rows
              items={[
                { label: "Subtotal", value: <Money value={{ amount: "58800.00", currency: "EUR" }} /> },
                { label: "Discount", value: <Money value={{ amount: "-2450.00", currency: "EUR" }} /> },
                { label: "Freight", value: <Money value={{ amount: "1250.00", currency: "EUR" }} /> },
                { label: "Total", value: <Money value={{ amount: "57600.00", currency: "EUR" }} />, total: true },
              ]}
            />
          </Panel>
        </div>
      </Group>

      <Group title="Schedule and timeline">
        <Panel>
          <Schedule
            label="Press line, Monday"
            start={8}
            end={20}
            lanes={[
              { label: "Press 1", blocks: [{ start: 8, end: 11.5, label: "Smoked walnut, 1.0 mm", avatar: "Arjun Mehta" }, { start: 12.5, end: 17, label: "Arctic white", tone: "gold" }] },
              { label: "Press 2", blocks: [{ start: 9, end: 13, label: "Concrete grey", tone: "glass" }, { at: 14, note: "Maintenance until 4 PM" }, { start: 16, end: 19.5, label: "Oak natural", avatar: "Kabir Rao" }] },
              { label: "Sanding and inspection", blocks: [{ start: 10, end: 12, label: "Batch 2291" }, { start: 13, end: 18, label: "Batch 2292 and 2293" }] },
            ]}
          />
        </Panel>
        <Panel>
          <Timeline
            label="Quotation activity"
            items={[
              { id: "a1", title: "Nordhaus Interiors accepted the quotation", meta: <DateText value="2026-10-12T03:10:00Z" style="dayTime" />, icon: "checkCircle", tone: "leaf" },
              { id: "a2", title: "Meera sent revision 2 to the customer", meta: <DateText value="2026-10-11T09:30:00Z" style="dayTime" />, body: "Freight reduced from EUR 1,600.00 to EUR 1,250.00 after the forwarder's new rate.", icon: "send", tone: "cobalt" },
              { id: "a3", title: "Sahil approved a 4% discount", meta: <DateText value="2026-10-10T12:05:00Z" style="dayTime" />, icon: "badgeCheck", tone: "gold" },
              { id: "a4", title: "Approval requested: discount above 3%", meta: <DateText value="2026-10-10T10:48:00Z" style="dayTime" />, icon: "alert", tone: "amber" },
              { id: "a5", title: "Meera created the quotation from enquiry LK-EN-2026-0127", meta: <DateText value="2026-10-09T05:20:00Z" style="dayTime" /> },
            ]}
          />
        </Panel>
      </Group>

      <Group title="Formatting">
        <Panel>
          <KeyValue
            columns={2}
            items={[
              { label: "Money", value: <Money value={{ amount: "5760.0000", currency: "EUR" }} /> },
              { label: "Money, compact", value: <Money value={{ amount: "1284500.00", currency: "INR" }} compact /> },
              { label: "Money, missing", value: <Money value={null} /> },
              { label: "Quantity", value: <Qty value={{ value: "2400.000000", uom: "sheets" }} /> },
              { label: "Date", value: <DateText value="2026-10-12T03:25:00Z" /> },
              { label: "Day and time", value: <DateText value="2026-10-12T03:25:00Z" style="dayTime" /> },
              { label: "Relative", value: <DateText value="2026-10-12T03:20:00Z" style="relative" /> },
              { label: "Business date", value: <DateText value="2026-10-26" style="business" /> },
              { label: "Code", value: <Code>LK-QT-2026-0041</Code> },
              { label: "Not set", value: <Dash /> },
            ]}
          />
        </Panel>
      </Group>
    </div>
  );
}
