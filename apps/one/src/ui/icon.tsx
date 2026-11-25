import {
  Activity, Archive, ArrowDownRight, ArrowLeft, ArrowRight, ArrowUpDown, ArrowUpRight, BadgeCheck, Banknote, Bell,
  Bookmark, Bot, Boxes, Building2, Calculator, Calendar, Camera, ChartColumn, ChartLine, Check, ChevronDown,
  ChevronLeft, ChevronRight, ChevronUp, CircleCheck, CircleDot, CircleHelp, CircleX, ClipboardCheck, ClipboardList,
  Clock, Columns3, Command, Container, Copy, CreditCard, Database, Download, Ellipsis, ExternalLink, Eye, EyeOff,
  Factory, File, FileCheck, FilePlus, FileSpreadsheet, FileText, Flag, FlaskConical, Gauge, Globe, GripVertical,
  Hammer, Handshake, Hash, History, House, Image, Inbox, Info, Key, Languages, Layers, LayoutGrid, Link2, List,
  ListFilter, Lock, LogOut, Mail, MapPin, Menu, Merge, MessageSquare, Mic, Minus, Monitor, Moon, Package,
  PackageOpen, Palette, PanelLeft, Paperclip, Pause, Pencil, Percent, Phone, Play, Plus, Printer, ReceiptText,
  RefreshCw, Route, Ruler, Save, ScanLine, Scissors, Search, Send, Settings, Shapes, Share2, ShieldCheck,
  ShoppingCart, SlidersHorizontal, Sparkles, Split, Square, Star, Sun, SwatchBook, Tag, ThumbsDown, ThumbsUp,
  Timer, Trash2, TriangleAlert, Truck, Undo2, Upload, UserCog, UserPlus, UserRound, Users, Wallet, Warehouse, X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import type { SVGAttributes } from "react";

/**
 * The Lamikraft icon set: 24-grid line glyphs with 1.75px round strokes (the design system's
 * setting), drawn from Lucide. Names are camelCase and stable; the first block keeps the design
 * system's 39 starter names, the second adds what the ERP needs. Never use filled or two-tone icons.
 */
const registry = {
  // design-system starter names
  home: House, chart: ChartColumn, box: Package, users: Users, settings: Settings, bell: Bell, search: Search,
  plus: Plus, check: Check, x: X, chevronDown: ChevronDown, chevronRight: ChevronRight, chevronLeft: ChevronLeft,
  arrowUpRight: ArrowUpRight, arrowDownRight: ArrowDownRight, arrowRight: ArrowRight, sparkles: Sparkles,
  paperclip: Paperclip, send: Send, mic: Mic, sun: Sun, moon: Moon, more: Ellipsis, filter: ListFilter,
  calendar: Calendar, download: Download, alert: TriangleAlert, info: Info, checkCircle: CircleCheck,
  cart: ShoppingCart, file: File, mail: Mail, sort: ArrowUpDown, grid: LayoutGrid, trash: Trash2, eye: Eye,
  clock: Clock, tag: Tag, layers: Layers,
  // ERP additions
  activity: Activity, archive: Archive, arrowLeft: ArrowLeft, badgeCheck: BadgeCheck, banknote: Banknote,
  bookmark: Bookmark, bot: Bot, boxes: Boxes, building: Building2, calculator: Calculator, camera: Camera,
  chartLine: ChartLine, chevronUp: ChevronUp, circleDot: CircleDot, clipboard: ClipboardList,
  clipboardCheck: ClipboardCheck, columns: Columns3, command: Command, container: Container, copy: Copy,
  creditCard: CreditCard, database: Database, edit: Pencil, external: ExternalLink, eyeOff: EyeOff,
  factory: Factory, fileCheck: FileCheck, filePlus: FilePlus, fileText: FileText, flag: Flag, flask: FlaskConical,
  gauge: Gauge, globe: Globe, grip: GripVertical, hammer: Hammer, handshake: Handshake, hash: Hash, help: CircleHelp,
  history: History, image: Image, inbox: Inbox, key: Key, languages: Languages, link: Link2, list: List, lock: Lock,
  logOut: LogOut, mapPin: MapPin, menu: Menu, merge: Merge, message: MessageSquare, minus: Minus, monitor: Monitor,
  packageOpen: PackageOpen, palette: Palette, panelLeft: PanelLeft, pause: Pause, percent: Percent, phone: Phone,
  play: Play, printer: Printer, receipt: ReceiptText, refresh: RefreshCw, route: Route, ruler: Ruler, save: Save,
  scan: ScanLine, scissors: Scissors, shapes: Shapes, share: Share2, shield: ShieldCheck, sliders: SlidersHorizontal,
  split: Split, spreadsheet: FileSpreadsheet, stop: Square, star: Star, swatch: SwatchBook, thumbsDown: ThumbsDown,
  thumbsUp: ThumbsUp, timer: Timer, truck: Truck, undo: Undo2, upload: Upload, user: UserRound, userCog: UserCog,
  userPlus: UserPlus, wallet: Wallet, warehouse: Warehouse, xCircle: CircleX, zap: Zap,
} as const satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof registry;
export const iconNames = Object.keys(registry) as IconName[];

export interface IconProps extends Omit<SVGAttributes<SVGSVGElement>, "name"> {
  name: IconName;
  /** Pixel size; 18 in controls, 20 in navigation, 16 in dense rows. */
  size?: number;
  strokeWidth?: number;
}

/** Decorative by default (aria-hidden). Pass `aria-label` when the icon is the only label. */
export function Icon({ name, size = 18, strokeWidth = 1.75, ...rest }: IconProps) {
  const Glyph = registry[name];
  const labelled = rest["aria-label"] !== undefined;
  return (
    <Glyph
      width={size}
      height={size}
      strokeWidth={strokeWidth}
      aria-hidden={labelled ? undefined : true}
      role={labelled ? "img" : undefined}
      focusable={false}
      {...rest}
    />
  );
}
