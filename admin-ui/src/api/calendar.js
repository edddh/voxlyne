import client from './client'

export const getAvailableSlots = async (callId, numSlots = 3) => {
  const response = await client.get(`/api/calendar/calls/${callId}/slots`, { params: { num_slots: numSlots } })
  return response.data
}

export const scheduleAppointment = async (data) => {
  const response = await client.post('/api/calendar/schedule', data)
  return response.data
}

export const cancelAppointment = async (callId, notifyAttendees = true) => {
  const response = await client.delete(`/api/calendar/calls/${callId}/appointment`, {
    params: { notify_attendees: notifyAttendees },
  })
  return response.data
}

export const getCalendarEvent = async (callId) => {
  const response = await client.get(`/api/calendar/calls/${callId}/event`)
  return response.data
}

export const getCalendarEvents = async (params = {}) => {
  const response = await client.get('/api/calendar/events', { params })
  return response.data
}

export const testCalendarConnection = async (data) => {
  const response = await client.post('/api/calendar/test-connection', data)
  return response.data
}

export const getCalendarProviders = async () => {
  const response = await client.get('/api/calendar/providers')
  return response.data
}
