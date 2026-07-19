import React, { useState, useEffect, useRef } from 'react';
import {
  getRiskScores,
  getScenarios,
  getProcurementRecs,
  getReservePlan,
  getPipelineStatus,
  runPipeline,
} from './api';
import MetricStrip from './components/MetricStrip';
import CorridorMap from './components/CorridorMap';
import ScenarioPanel from './components/ScenarioPanel';
import DrawdownChart from './components/DrawdownChart';
import ProcurementTable from './components/ProcurementTable';
import RiskExplanationPanel from './components/RiskExplanationPanel';

function App() {
  const [riskScores, setRiskScores] = useState([]);
  const [scenarios, setScenarios] = useState([]);
  const [activeScenario, setActiveScenario] = useState(null);
  const [activeReservePlan, setActiveReservePlan] = useState(null);
  const [activeRecs, setActiveRecs] = useState([]);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [selectedCorridor, setSelectedCorridor] = useState('hormuz');
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Pipeline execution state
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineElapsed, setPipelineElapsed] = useState(0);
  const timerRef = useRef(null);

  const fetchData = async (isBackground = false) => {
    if (!isBackground) setLoading(true);
    setError(null);
    try {
      // 1. Fetch main datasets
      const scoresData = await getRiskScores();
      const scenariosData = await getScenarios();
      
      let statusData = null;
      try {
        statusData = await getPipelineStatus();
      } catch (err) {
        console.warn("Pipeline status not recorded yet:", err);
      }

      setRiskScores(scoresData || []);
      setScenarios(scenariosData || []);
      setPipelineStatus(statusData);

      // Check if we have data to work with
      if (!scoresData || scoresData.length === 0 || !scenariosData || scenariosData.length === 0) {
        setError("No data loaded in the system yet. Please click 'Run Pipeline Now' in the header to initialize the backend database.");
        setLoading(false);
        return;
      }

      // 2. Determine active scenario
      // If we already have an active scenario, keep its type if it exists in the new list,
      // otherwise default to the highest severity scenario.
      let currentActive = null;
      if (activeScenario) {
        currentActive = scenariosData.find(s => s.scenario_type === activeScenario.scenario_type);
      }
      
      if (!currentActive && scenariosData.length > 0) {
        // Sort by severity descending to find the highest severity scenario
        const sorted = [...scenariosData].sort((a, b) => b.severity - a.severity);
        currentActive = sorted[0];
      }

      if (currentActive) {
        setActiveScenario(currentActive);
        
        // 3. Fetch secondary data for active scenario
        try {
          const recsData = await getProcurementRecs(currentActive.id);
          setActiveRecs(recsData || []);
        } catch (err) {
          console.warn("Could not load procurement recs:", err);
          setActiveRecs([]);
        }

        try {
          const reserveData = await getReservePlan(currentActive.id);
          setActiveReservePlan(reserveData);
        } catch (err) {
          console.warn("Could not load reserve plan:", err);
          setActiveReservePlan(null);
        }
      }
    } catch (err) {
      console.error("Error fetching dashboard data:", err);
      setError("Failed to connect to the energy resilience API backend. Make sure the FastAPI server is running at http://localhost:8000.");
    } finally {
      if (!isBackground) setLoading(false);
    }
  };

  // Initial fetch
  useEffect(() => {
    fetchData();
  }, []);

  // Polling loop: every 30s
  useEffect(() => {
    const interval = setInterval(() => {
      if (!pipelineRunning) {
        fetchData(true);
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [pipelineRunning, activeScenario]);

  // Handle manual scenario switch
  const handleSelectScenarioType = async (scenarioType) => {
    const targetScenario = scenarios.find(s => s.scenario_type === scenarioType);
    if (!targetScenario) return;

    setActiveScenario(targetScenario);
    setActiveRecs([]);
    setActiveReservePlan(null);

    try {
      const recsData = await getProcurementRecs(targetScenario.id);
      setActiveRecs(recsData || []);
    } catch (err) {
      console.warn("Could not load procurement recs:", err);
    }

    try {
      const reserveData = await getReservePlan(targetScenario.id);
      setActiveReservePlan(reserveData);
    } catch (err) {
      console.warn("Could not load reserve plan:", err);
    }
  };

  // Handle pipeline run trigger
  const handleRunPipeline = async () => {
    if (pipelineRunning) return;

    setPipelineRunning(true);
    setPipelineElapsed(0);

    // Start elapsed timer UI
    timerRef.current = setInterval(() => {
      setPipelineElapsed(prev => prev + 1);
    }, 1000);

    try {
      await runPipeline();
      await fetchData();
    } catch (err) {
      console.error("Error executing pipeline:", err);
      alert("Failed to run pipeline. Verify FastAPI server logs.");
    } finally {
      clearInterval(timerRef.current);
      setPipelineRunning(false);
    }
  };

  // Extract variables for components
  const hormuzRisk = riskScores.find(r => r.corridor === 'hormuz');
  const redSeaRisk = riskScores.find(r => r.corridor === 'red_sea');

  // Find the highest severity scenario to calculate SPR days remaining for MetricStrip
  const highestSeverityScenario = [...scenarios].sort((a, b) => b.severity - a.severity)[0];
  
  // Local state or fetch helper to get the highest severity scenario's reserve plan
  const [highestReservePlan, setHighestReservePlan] = useState(null);

  useEffect(() => {
    const fetchHighestReserve = async () => {
      if (highestSeverityScenario) {
        try {
          const res = await getReservePlan(highestSeverityScenario.id);
          setHighestReservePlan(res);
        } catch (e) {
          setHighestReservePlan(null);
        }
      } else {
        setHighestReservePlan(null);
      }
    };
    fetchHighestReserve();
  }, [scenarios]);

  const sprDaysRemaining = highestReservePlan?.days_of_cover_remaining;
  const pipelineLatency = pipelineStatus?.total_latency_seconds;

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="header-info">
          <div className="header-logo">
            <span className="logo-pulse"></span>
            <h1>Energy Supply Chain Resilience</h1>
          </div>
          <p className="header-tagline">Stage 8 Geopolitical Disruption Geotemporal Dashboard</p>
        </div>
        
        <button 
          className={`run-pipeline-btn ${pipelineRunning ? 'btn-running' : ''}`}
          onClick={handleRunPipeline}
          disabled={pipelineRunning}
        >
          {pipelineRunning ? (
            <>
              <span className="spinner"></span>
              Running Pipeline ({pipelineElapsed}s)
            </>
          ) : (
            'Run Pipeline Now'
          )}
        </button>
      </header>

      {/* Main Layout Content */}
      {loading ? (
        <div className="fullscreen-state">
          <div className="spinner-large"></div>
          <p>Analyzing supply chain corridors and loading risk data...</p>
        </div>
      ) : error ? (
        <div className="fullscreen-state error-state">
          <div className="error-card">
            <svg className="error-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <h3>Data Ingestion Status</h3>
            <p>{error}</p>
            {!pipelineRunning && (
              <button className="error-action-btn" onClick={handleRunPipeline}>
                Initialize & Run Pipeline Now
              </button>
            )}
          </div>
        </div>
      ) : (
        <main className="dashboard-grid">
          {/* Top Metrics Row */}
          <MetricStrip
            hormuzRisk={hormuzRisk}
            redSeaRisk={redSeaRisk}
            sprDaysRemaining={sprDaysRemaining}
            pipelineLatency={pipelineLatency}
          />

          {/* Map + Scenario / Drawdown Row */}
          <div className="dashboard-row-two-col">
            <CorridorMap
              hormuzRisk={hormuzRisk}
              redSeaRisk={redSeaRisk}
              onSelectCorridor={setSelectedCorridor}
            />
            
            <div className="right-panel-stack">
              <ScenarioPanel
                scenarios={scenarios}
                activeScenario={activeScenario}
                activeReservePlan={activeReservePlan}
                onSelectScenarioType={handleSelectScenarioType}
              />
              <DrawdownChart
                activeReservePlan={activeReservePlan}
                activeScenario={activeScenario}
              />
            </div>
          </div>

          {/* Sourcing Recommendations Table */}
          <ProcurementTable
            recommendations={activeRecs}
            activeScenario={activeScenario}
          />

          {/* Gemini AI Detailed Risk Report */}
          <RiskExplanationPanel
            selectedCorridor={selectedCorridor}
            hormuzRisk={hormuzRisk}
            redSeaRisk={redSeaRisk}
          />
        </main>
      )}
    </div>
  );
}

export default App;
