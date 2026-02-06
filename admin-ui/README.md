# Admin Panel - Ascolta

Pannello di amministrazione per il sistema di interviste telefoniche AI.

## Funzionalità

### Autenticazione e Utenti
- ✅ Login con JWT (access + refresh token)
- ✅ Gestione utenti con ruoli (super_admin, admin, creator, power_user, user)
- ✅ Multi-tenancy con isolamento dati

### Dashboard
- ✅ Statistiche in tempo reale
- ✅ Grafici trend chiamate
- ✅ Tabella statistiche progetti

### Gestione Progetti
- ✅ CRUD completo progetti
- ✅ Editor prompt A (intervista) e B (estrazione)
- ✅ Versioning prompt con storico completo
- ✅ Attivazione/rollback versioni
- ✅ Diff tra versioni (unified diff colorato)

### Gestione Chiamate
- ✅ Lista chiamate con filtri avanzati
- ✅ Dettaglio chiamata con transcript interattivo
- ✅ Visualizzazione record JSON
- ✅ Download PDF report

### Integrazioni
- ✅ **CRM (HubSpot)**: Configurazione completa con test connessione
- ✅ **Calendar**: Google Calendar e Microsoft Outlook/365

### Tenant Management (Solo Super Admin)
- ✅ Gestione tenant
- ✅ Configurazione multi-tenant

## Stack Tecnologico

- **React 18.3** - UI framework
- **Vite 5.4** - Build tool e dev server
- **Ant Design 5.22** - Component library
- **React Router DOM 7** - Routing
- **Axios** - HTTP client con interceptor per token refresh
- **Context API** - State management per autenticazione

## Setup e Avvio

### Prerequisiti
- Node.js 18+
- Backend FastAPI avviato su `http://localhost:8000`

### Installazione
```bash
cd admin-ui
npm install
```

### Avvio Development Server
```bash
npm run dev
```

L'applicazione sarà disponibile su `http://localhost:5173`

### Build per Produzione
```bash
npm run build
```

I file ottimizzati saranno generati in `dist/`

### Preview Build di Produzione
```bash
npm run preview
```

## Configurazione

### Proxy API
Il proxy verso il backend è configurato in `vite.config.js`:
```javascript
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true
  }
}
```

### Variabili d'Ambiente
Opzionalmente puoi creare un file `.env`:
```env
VITE_API_URL=http://localhost:8000
```

## Struttura Directory

```
admin-ui/
├── src/
│   ├── api/              # API client modules
│   │   ├── client.js     # Axios instance con interceptor
│   │   ├── auth.js       # Auth endpoints
│   │   ├── users.js      # Users CRUD
│   │   ├── tenants.js    # Tenants CRUD
│   │   ├── projects.js   # Projects CRUD
│   │   ├── prompts.js    # Prompt versioning
│   │   ├── calls.js      # Calls API
│   │   ├── analytics.js  # Dashboard stats
│   │   ├── crm.js        # HubSpot integration
│   │   └── calendar.js   # Calendar integration
│   ├── hooks/
│   │   └── useAuth.jsx   # Auth context e hook
│   ├── layouts/
│   │   └── AppLayout.jsx # Layout con sidebar e header
│   ├── pages/            # Page components
│   │   ├── Login.jsx
│   │   ├── Dashboard.jsx
│   │   ├── Users.jsx
│   │   ├── Tenants.jsx
│   │   ├── Projects.jsx
│   │   ├── ProjectEdit.jsx
│   │   ├── PromptHistory.jsx
│   │   ├── Calls.jsx
│   │   ├── CallDetail.jsx
│   │   ├── CRMIntegration.jsx
│   │   └── CalendarIntegration.jsx
│   ├── App.jsx           # Routes
│   └── main.jsx          # Entry point
├── package.json
├── vite.config.js
└── index.html
```

## Ruoli e Permessi

| Ruolo | Permessi |
|-------|----------|
| `super_admin` | Accesso completo, gestione tenant |
| `admin` | Gestione utenti, progetti, prompt |
| `creator` | Creazione e modifica progetti e prompt |
| `power_user` | Visualizzazione avanzata, analytics |
| `user` | Visualizzazione base |

## Credenziali Default

Dopo aver eseguito la migration `005_admin_panel.sql`:

- **Email**: `admin@example.test`
- **Password**: `password-set-at-bootstrap`
- **Ruolo**: `super_admin`

⚠️ **Importante**: Cambiare password subito dopo il primo accesso!

## API Backend Richieste

Il frontend si aspetta questi endpoint dal backend:

### Auth
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/auth/change-password`

### Users
- `GET /api/users`
- `GET /api/users/{id}`
- `POST /api/users`
- `PATCH /api/users/{id}`
- `DELETE /api/users/{id}`

### Tenants (super_admin only)
- `GET /api/tenants`
- `GET /api/tenants/{id}`
- `POST /api/tenants`
- `PATCH /api/tenants/{id}`
- `DELETE /api/tenants/{id}`

### Projects & Prompts
- `GET /api/projects`
- `GET /api/projects/{id}`
- `POST /api/projects`
- `PATCH /api/projects/{id}`
- `DELETE /api/projects/{id}`
- `GET /api/projects/{id}/prompts/{type}/versions`
- `POST /api/projects/{id}/prompts/{type}/versions`
- `POST /api/prompts/versions/{id}/activate`
- `POST /api/prompts/versions/{id}/rollback`
- `GET /api/prompts/versions/{id_a}/diff/{id_b}`

### Calls
- `GET /api/v2/calls`
- `GET /api/v2/calls/{id}`
- `GET /api/v2/calls/{id}/transcript`
- `GET /api/v2/calls/{id}/pdf`

### Analytics
- `GET /api/analytics/dashboard`
- `GET /api/analytics/calls/trends`

### CRM
- `GET /api/crm/config`
- `PUT /api/crm/config`
- `POST /api/crm/test`

### Calendar
- `GET /api/calendar/config`
- `PUT /api/calendar/config/{provider}`
- `GET /api/calendar/{provider}/oauth-url`

## Note di Sviluppo

### Token Refresh Automatico
Il client axios include un interceptor che:
1. Intercetta risposte 401
2. Tenta refresh del token
3. Riprova la richiesta originale
4. Se il refresh fallisce, redirect a login

### Tenant Isolation
Tutte le richieste API includono automaticamente il contesto tenant dell'utente loggato. Il backend si occupa di filtrare i dati per tenant.

### Prompt Versioning
Il sistema mantiene uno storico completo delle versioni:
- Ogni modifica crea una nuova versione
- Solo una versione per tipo (A/B) può essere attiva
- Il rollback crea una nuova versione con contenuto precedente
- Il diff usa unified format con evidenziazione colori

## Troubleshooting

### CORS Errors
Assicurati che il backend FastAPI abbia configurato CORS correttamente per `http://localhost:5173`

### 401 Unauthorized Loop
- Verifica che il JWT secret sia configurato correttamente
- Controlla che i token non siano scaduti
- Pulisci localStorage: `localStorage.clear()`

### Proxy Non Funziona
- Riavvia il dev server di Vite
- Verifica che il backend sia in ascolto su porta 8000
- Controlla `vite.config.js` per configurazione proxy

## Licenza

Proprietario - Edgardo Di Nicola Carena
