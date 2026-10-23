import type { ComponentType } from "react";
import {
  FinanceIcon,
  InboxIcon,
  MoreIcon,
  OperationsIcon,
  ProductsIcon,
  SalesIcon,
  SettingsIcon,
  TodayIcon,
  WorkIcon,
  type IconProps,
} from "@/components/ui/icons";

const ICONS: Record<string, ComponentType<IconProps>> = {
  today: TodayIcon,
  inbox: InboxIcon,
  sales: SalesIcon,
  products: ProductsIcon,
  operations: OperationsIcon,
  finance: FinanceIcon,
  settings: SettingsIcon,
  work: WorkIcon,
  more: MoreIcon,
};

export function AreaIcon({ id, ...props }: IconProps & { id: string }) {
  const Icon = ICONS[id] ?? WorkIcon;
  return <Icon {...props} />;
}
