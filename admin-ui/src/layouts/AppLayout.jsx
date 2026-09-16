import { useState, useEffect } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Space, Button, Grid } from 'antd'
import {
  DashboardOutlined,
  UserOutlined,
  TeamOutlined,
  ProjectOutlined,
  PhoneOutlined,
  SettingOutlined,
  LogoutOutlined,
  ApiOutlined,
  CalendarOutlined,
  ProfileOutlined,
  RiseOutlined,
} from '@ant-design/icons'
import { useAuth } from '../hooks/useAuth'
import { BRAND } from '../main'
import { BrandLogo } from '../components/BrandLogo'

const { Header, Sider, Content } = Layout

// Hamburger di marca: 3 righe bianche, l'ultima arancione (accento Ascolta,
// lo stesso usato ovunque nel resto dell'interfaccia) - al posto delle
// icone antd generiche MenuFold/MenuUnfold. maintainer, 19/08: "il toast
// [= il pulsante del menu] dovrebbe essere esteticamente come quella
// del sito con linee bianche l'ultima arancione".
function MenuToggleIcon() {
  const barStyle = { display: 'block', width: 18, height: 2, borderRadius: 1 }
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 4, cursor: 'pointer' }}>
      <span style={{ ...barStyle, background: BRAND.white }} />
      <span style={{ ...barStyle, background: BRAND.white }} />
      <span style={{ ...barStyle, background: BRAND.orange }} />
    </span>
  )
}

function AppLayout() {
  const screens = Grid.useBreakpoint()
  // antd riporta i breakpoint come oggetto con chiavi progressive
  // (xs/sm/md/lg/xl/xxl); finche' non arriva la prima misurazione reale
  // dal browser, screens.lg e' undefined - trattarlo come "non ancora
  // so, assumo desktop" evita un lampo di sidebar aperta su schermi
  // piccoli al primo render.
  const isMobile = screens.lg === false
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout, isSuperAdmin, isAdmin } = useAuth()

  // Sidebar chiusa di default su mobile (era sempre aperta, a
  // larghezza fissa, su qualunque schermo - inutilizzabile su telefono:
  // maintainer, 18/08, "su mobile il sito e' difficilmente usabile").
  // Su desktop resta aperta di default come prima.
  useEffect(() => {
    setCollapsed(isMobile)
  }, [isMobile])

  // Richiudi automaticamente la sidebar-overlay su mobile dopo aver
  // scelto una voce di menu - altrimenti resta aperta sopra la pagina
  // appena caricata.
  useEffect(() => {
    if (isMobile) setCollapsed(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  const menuItems = [
    // Stessi ruoli richiesti dal backend (app/routers/analytics.py:34,
    // GET /api/analytics/dashboard) - creator e user ricevevano solo un
    // 403 inghiottito in silenzio dalla pagina, che si vedeva come una
    // dashboard sempre a zero invece che come "non hai accesso".
    ['admin', 'super_admin', 'power_user'].includes(user?.role) && {
      key: '/',
      icon: <DashboardOutlined />,
      label: 'Dashboard',
    },
    {
      key: '/calls',
      icon: <PhoneOutlined />,
      label: 'Chiamate',
    },
    ['admin', 'super_admin', 'power_user'].includes(user?.role) && {
      key: '/analytics',
      icon: <RiseOutlined />,
      label: 'Analytics',
    },
    {
      key: '/projects',
      icon: <ProjectOutlined />,
      label: 'Progetti',
    },
    isAdmin && {
      key: '/users',
      icon: <UserOutlined />,
      label: 'Utenti',
    },
    // Il super_admin gestisce le credenziali di ogni tenant dalla lista
    // Tenant (icona per riga) - qui serve solo per l'admin del proprio
    // tenant, che altrimenti non ha alcuna via per raggiungere una pagina
    // che esiste ed e' gia' protetta correttamente lato backend.
    user?.role === 'admin' && {
      key: `/tenants/${user.tenant_id}/credentials`,
      icon: <ApiOutlined />,
      label: 'Credenziali',
    },
    isSuperAdmin && {
      key: '/tenants',
      icon: <TeamOutlined />,
      label: 'Tenant',
    },
    isSuperAdmin && {
      key: '/templates',
      icon: <ProfileOutlined />,
      label: 'Template',
    },
    {
      key: 'integrations',
      icon: <ApiOutlined />,
      label: 'Integrazioni',
      children: [
        {
          key: '/integrations/crm',
          icon: <ApiOutlined />,
          label: 'CRM (HubSpot)',
        },
        {
          key: '/integrations/calendar',
          icon: <CalendarOutlined />,
          label: 'Calendario',
        },
      ],
    },
  ].filter(Boolean)

  const userMenu = {
    items: [
      {
        // maintainer, 20/08: "ma profilo impostazioni in alto a destra non
        // fa nulla" - puntavano a /profile e /settings, mai registrate
        // in App.jsx: si tornava silenziosamente alla Dashboard.
        // "Impostazioni" fusa qui dentro (nessun concetto di impostazioni
        // personali esiste ancora lato backend) - un solo link, dati
        // account + cambio password, quello che il backend supporta gia'.
        key: 'profile',
        icon: <UserOutlined />,
        label: 'Profilo',
        onClick: () => navigate('/profile'),
      },
      {
        type: 'divider',
      },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: 'Esci',
        danger: true,
        onClick: logout,
      },
    ],
  }

  const roleLabels = {
    super_admin: 'Super Admin',
    admin: 'Admin',
    creator: 'Creator',
    power_user: 'Power User',
    user: 'User',
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      {/* Backdrop: solo su mobile, solo a sidebar aperta - tocca fuori
          per richiuderla, come qualunque drawer. Su desktop la sidebar
          spinge il contenuto come prima, nessun backdrop. */}
      {isMobile && !collapsed && (
        <div
          onClick={() => setCollapsed(true)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.5)',
            zIndex: 999,
          }}
        />
      )}
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        collapsedWidth={isMobile ? 0 : 80}
        theme="dark"
        style={{
          background: BRAND.bg,
          borderRight: `1px solid ${BRAND.border}`,
          ...(isMobile
            ? { position: 'fixed', top: 0, left: 0, height: '100vh', zIndex: 1000, overflow: 'auto' }
            : {}),
        }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: collapsed ? 0 : '0 16px',
            borderBottom: `1px solid ${BRAND.border}`,
            overflow: 'hidden',
          }}
        >
          {collapsed ? (
            <span style={{ color: BRAND.orange, fontSize: 20, fontWeight: 700 }}>AT</span>
          ) : (
            <BrandLogo alt="Ascolta" style={{ maxWidth: '100%', height: 32, objectFit: 'contain' }} />
          )}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => {
            if (!key.startsWith('integrations')) {
              navigate(key)
            }
          }}
        />
      </Sider>
      <Layout style={isMobile ? { marginLeft: 0 } : undefined}>
        <Header
          style={{
            padding: '0 12px',
            background: BRAND.bgElevated,
            borderBottom: `1px solid ${BRAND.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'sticky',
            top: 0,
            zIndex: 998,
          }}
        >
          <Button
            type="text"
            icon={<MenuToggleIcon />}
            onClick={() => setCollapsed(!collapsed)}
          />
          <Space>
            <Dropdown menu={userMenu} placement="bottomRight">
              <Space style={{ cursor: 'pointer' }}>
                <Avatar style={{ backgroundColor: BRAND.orange, color: BRAND.bg, fontWeight: 700 }}>
                  {user?.full_name?.charAt(0) || user?.email?.charAt(0)?.toUpperCase()}
                </Avatar>
                {/* Nome/ruolo per esteso solo dove c'e' spazio - su
                    schermi stretti restano solo l'avatar e il menu a
                    tendina, gia' sufficienti per accedere a profilo/logout. */}
                {screens.sm && (
                  <div style={{ lineHeight: 1.2 }}>
                    <div style={{ fontWeight: 500, color: BRAND.white }}>{user?.full_name || user?.email}</div>
                    <div style={{ fontSize: 12, color: BRAND.textDim }}>{roleLabels[user?.role]}</div>
                  </div>
                )}
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content
          style={{
            margin: isMobile ? 12 : 24,
            padding: isMobile ? 12 : 24,
            background: BRAND.bgContainer,
            border: `1px solid ${BRAND.border}`,
            borderRadius: 8,
            minHeight: 280,
            // Se una pagina contiene qualcosa di piu' largo dello
            // schermo (tabella, codice...) scorre qui dentro, non tutta
            // la pagina in orizzontale.
            overflowX: 'auto',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}

export default AppLayout
