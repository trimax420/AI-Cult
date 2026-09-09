import {
  BellIcon,
  WorkflowIcon,
  ClipboardListIcon,
  FilmIcon,
  LayoutDashboardIcon,
  ShieldAlertIcon,
  WrenchIcon,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type DashboardView = "overview" | "incidents" | "recovery" | "audit" | "architecture"

type AppSidebarProps = {
  activeView?: DashboardView
  incidentCount?: number
  onNavigate?: (view: DashboardView) => void
}

const nav = [
  { label: "Production Portfolio", icon: LayoutDashboardIcon, view: "overview" as const },
  { label: "Production Risks", icon: ShieldAlertIcon, view: "incidents" as const },
  { label: "Decisions & Actions", icon: WrenchIcon, view: "recovery" as const },
  { label: "Audit", icon: ClipboardListIcon, view: "audit" as const },
  { label: "How it works", icon: WorkflowIcon, view: "architecture" as const },
]

export function AppSidebar({ activeView = "overview", incidentCount = 0, onNavigate = () => undefined }: AppSidebarProps) {
  const { isMobile, setOpenMobile } = useSidebar()

  function navigate(view: DashboardView) {
    onNavigate(view)
    if (isMobile) setOpenMobile(false)
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="brand-header">
        <div className="brand-mark"><FilmIcon /></div>
        <div className="brand-copy"><strong>ReelWarden</strong><span>Protect every delivery</span></div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {nav.map((item) => (
                <SidebarMenuItem key={item.label}>
                  <SidebarMenuButton
                    tooltip={item.label}
                    isActive={activeView === item.view}
                    aria-current={activeView === item.view ? "page" : undefined}
                    onClick={() => navigate(item.view)}
                  >
                    <item.icon />
                    <span>{item.label}</span>
                  </SidebarMenuButton>
                  {item.view === "incidents" && incidentCount > 0 ? (
                    <SidebarMenuBadge>{incidentCount}</SidebarMenuBadge>
                  ) : null}
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem><SidebarMenuButton tooltip="Notifications" onClick={() => navigate("audit")}><BellIcon /><span>Notifications</span></SidebarMenuButton></SidebarMenuItem>
          <li className="px-2 py-2 text-xs text-muted-foreground">Demo operator</li>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
