import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

export const getRiskScores = () => 
  apiClient.get('/api/risk-scores').then(res => res.data);

export const getScenarios = () => 
  apiClient.get('/api/scenarios').then(res => res.data);

export const getProcurementRecs = (scenarioId) => 
  apiClient.get(`/api/procurement-recs?scenario_id=${scenarioId}`).then(res => res.data);

export const getReservePlan = (scenarioId) => 
  apiClient.get(`/api/reserve-plan?scenario_id=${scenarioId}`).then(res => res.data);

export const getPipelineStatus = () => 
  apiClient.get('/api/pipeline-status').then(res => res.data);

export const runPipeline = () => 
  apiClient.post('/api/pipeline/run').then(res => res.data);
