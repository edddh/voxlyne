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
} from '@ant-design/icons'
import { useAuth } from '../hooks/useAuth'

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
    isSuperAdmin && {
      key: '/tenants',
      icon: <TeamOutlined />,
      label: 'Tenant',
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
        style={{ background: '#001529' }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white',
            fontSize: collapsed ? 16 : 18,
            fontWeight: 'bold',
            borderBottom: '1px solid rgba(255,255,255,0.1)',
          }}
        >
          {collapsed ? 'XC' : 'Ascolta'}
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
            background: '#fff',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            boxShadow: '0 1px 4px rgba(0,0,0,0.1)',
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
            style={{ fontSize: 16 }}
          />
          <Space>
            <Dropdown menu={userMenu} placement="bottomRight">
              <Space style={{ cursor: 'pointer' }}>
                <Avatar style={{ backgroundColor: '#1890ff' }}>
                  {user?.full_name?.charAt(0) || user?.email?.charAt(0)?.toUpperCase()}
                </Avatar>
                <div style={{ lineHeight: 1.2 }}>
                  <div style={{ fontWeight: 500 }}>{user?.full_name || user?.email}</div>
                  <div style={{ fontSize: 12, color: '#888' }}>{roleLabels[user?.role]}</div>
                </div>
              </Space>
            </Dropdown>
          </Space>
        </Header>
        <Content
          style={{
            margin: 24,
            padding: 24,
            background: '#fff',
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
