import {
  ActivityIcon,
  BellIcon,
  CircleGaugeIcon,
  ClipboardListIcon,
  FilmIcon,
  SettingsIcon,
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

export type DashboardView = "overview" | "incidents"

type AppSidebarProps = {
  activeView: DashboardView
  incidentCount: number
  onNavigate: (view: DashboardView, sectionId?: string) => void
}

const nav = [
  { label: "Overview", icon: CircleGaugeIcon, view: "overview" as const },
  { label: "Incidents", icon: ShieldAlertIcon, view: "incidents" as const },
  { label: "Recovery", icon: WrenchIcon, view: "overview" as const, sectionId: "recovery" },
  { label: "Audit", icon: ClipboardListIcon, view: "overview" as const, sectionId: "audit" },
]

export function AppSidebar({ activeView, incidentCount, onNavigate }: AppSidebarProps) {
  const { isMobile, setOpenMobile } = useSidebar()

  function navigate(view: DashboardView, sectionId?: string) {
    onNavigate(view, sectionId)
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
                    isActive={activeView === item.view && !item.sectionId}
                    onClick={() => navigate(item.view, item.sectionId)}
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
          <SidebarMenuItem><SidebarMenuButton tooltip="Notifications"><BellIcon /><span>Notifications</span></SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton tooltip="Settings"><SettingsIcon /><span>Settings</span></SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton tooltip="Operator profile"><ActivityIcon /><span>Ops Operator</span></SidebarMenuButton></SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
