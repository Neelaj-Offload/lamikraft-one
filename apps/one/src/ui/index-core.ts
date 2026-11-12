/** The core half of the Lamikraft component library: surfaces, actions, navigation, feedback, overlays. */

export { GlassPanel, type GlassPanelProps } from "./glass-panel";

export {
  Button,
  ButtonLink,
  IconButton,
  IconButtonLink,
  type ButtonLinkProps,
  type ButtonProps,
  type ButtonSize,
  type ButtonVariant,
  type IconButtonLinkProps,
  type IconButtonProps,
  type IconButtonVariant,
} from "./button";
export { ExternalLink, TextLink, type ExternalLinkProps, type TextLinkProps } from "./link";

export { Chip, ChipGroup, ChipLink, type ChipGroupProps, type ChipLinkProps, type ChipProps } from "./chip";
export {
  SegmentedControl,
  SegmentedLinks,
  type SegmentedControlProps,
  type SegmentedLinkOption,
  type SegmentedLinksProps,
  type SegmentedOption,
} from "./segmented";
export { TabPanel, Tabs, type TabItem, type TabPanelProps, type TabsProps } from "./tabs";
export { Breadcrumb, type BreadcrumbItem, type BreadcrumbProps } from "./breadcrumb";
export { PageSummary, Pagination, type PageSummaryProps, type PaginationProps } from "./pagination";

export { Badge, type BadgeProps, type Tone } from "./badge";
export { Avatar, AvatarGroup, type AvatarGroupProps, type AvatarProps, type AvatarSize } from "./avatar";
export { Banner, type BannerProps, type BannerTone } from "./banner";
export { LiveAnnouncer, toast, ToastRegion, type ToastContent, type ToastRegionProps, type ToastTone } from "./toast";
export { Tooltip, type TooltipProps } from "./tooltip";

export {
  ConfirmDialog,
  Drawer,
  Modal,
  ReasonDialog,
  type ConfirmDialogProps,
  type DrawerProps,
  type ModalProps,
  type ReasonDialogProps,
} from "./modal";
export { Menu, Popover, type MenuAction, type MenuItem, type MenuProps, type PopoverProps } from "./menu";

export { Skeleton, SkeletonRows, SkeletonText, type SkeletonProps, type SkeletonRowsProps, type SkeletonTextProps } from "./skeleton";
export { EmptyState, type EmptyStateProps } from "./empty-state";

export { Aurora, Composer, Orb, type AuroraProps, type ComposerProps, type OrbProps, type OrbState } from "./ai";
export { ThemeToggle, type ThemeToggleProps } from "./theme-toggle";
