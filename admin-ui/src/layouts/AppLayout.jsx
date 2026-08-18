import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Space, Button } from 'antd'
import {
  DashboardOutlined,
  UserOutlined,
  TeamOutlined,
  ProjectOutlined,
  PhoneOutlined,
  SettingOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ApiOutlined,
  CalendarOutlined,
  ProfileOutlined,
} from '@ant-design/icons'
import { useAuth } from '../hooks/useAuth'
import { BRAND } from '../main'
import logo from '../assets/ascolta-logo.png'

const { Header, Sider, Content } = Layout

function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout, isSuperAdmin, isAdmin } = useAuth()

  const menuItems = [
    {
      key: '/',
      icon: <DashboardOutlined />,
      label: 'Dashboard',
    },
    {
      key: '/calls',
      icon: <PhoneOutlined />,
      label: 'Chiamate',
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
        key: 'profile',
        icon: <UserOutlined />,
        label: 'Profilo',
        onClick: () => navigate('/profile'),
      },
      {
        key: 'settings',
        icon: <SettingOutlined />,
        label: 'Impostazioni',
        onClick: () => navigate('/settings'),
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
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        theme="dark"
        style={{ background: BRAND.bg, borderRight: `1px solid ${BRAND.border}` }}
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
            <img src={logo} alt="Ascolta" style={{ maxWidth: '100%', height: 32, objectFit: 'contain' }} />
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
      <Layout>
        <Header
          style={{
            padding: '0 24px',
            background: BRAND.bgElevated,
            borderBottom: `1px solid ${BRAND.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
            style={{ fontSize: 16, color: BRAND.white }}
          />
          <Space>
            <Dropdown menu={userMenu} placement="bottomRight">
              <Space style={{ cursor: 'pointer' }}>
                <Avatar style={{ backgroundColor: BRAND.orange, color: BRAND.bg, fontWeight: 700 }}>
                  {user?.full_name?.charAt(0) || user?.email?.charAt(0)?.toUpperCase()}
                </Avatar>
                <div style={{ lineHeight: 1.2 }}>
                  <div style={{ fontWeight: 500, color: BRAND.white }}>{user?.full_name || user?.email}</div>
                  <div style={{ fontSize: 12, color: BRAND.textDim }}>{roleLabels[user?.role]}</div>
                </div>
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content
          style={{
            margin: 24,
            padding: 24,
            background: BRAND.bgContainer,
            border: `1px solid ${BRAND.border}`,
            borderRadius: 8,
            minHeight: 280,
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}

export default AppLayout
