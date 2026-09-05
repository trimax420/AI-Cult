import {
  BellIcon,
  CircleGaugeIcon,
  ClipboardListIcon,
  FilmIcon,
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

export type DashboardView = "overview" | "incidents" | "recovery" | "audit"

type AppSidebarProps = {
  activeView?: DashboardView
  incidentCount?: number
  onNavigate?: (view: DashboardView) => void
}

const nav = [
  { label: "Overview", icon: CircleGaugeIcon, view: "overview" as const },
  { label: "Incidents", icon: ShieldAlertIcon, view: "incidents" as const },
  { label: "Recovery", icon: WrenchIcon, view: "recovery" as const },
  { label: "Audit", icon: ClipboardListIcon, view: "audit" as const },
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
        <div className="brand-copy"><strong>AI Production</strong><span>Director</span></div>
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
