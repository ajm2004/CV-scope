import { Navigate, Route, Routes } from "react-router";
import Layout from "./components/Layout";
import AnalysisPage from "./pages/AnalysisPage";
import AnomaliesPage from "./pages/AnomaliesPage";
import AnomalyAssistantPage from "./pages/AnomalyAssistantPage";
import CamerasPage from "./pages/CamerasPage";
import DataPage from "./pages/DataPage";
import ExperimentPage from "./pages/ExperimentPage";
import ExperimentsPage from "./pages/ExperimentsPage";
import GuidePage from "./pages/GuidePage";
import GuidesPage from "./pages/GuidesPage";
import HardwarePage from "./pages/HardwarePage";
import HomeRedirect from "./pages/HomeRedirect";
import LivePage from "./pages/LivePage";
import ModelsPage from "./pages/ModelsPage";
import ProjectPage from "./pages/ProjectPage";
import ProjectsPage from "./pages/ProjectsPage";
import ReviewPage from "./pages/ReviewPage";
import RunAnalysisPage from "./pages/RunAnalysisPage";
import SettingsPage from "./pages/SettingsPage";
import SetupPage from "./pages/SetupPage";
import PeoplePage from "./recognition/PeoplePage";
import RecognitionEventsPage from "./recognition/RecognitionEventsPage";
import RecognitionSettingsPage from "./recognition/RecognitionSettingsPage";
import RecognitionTestPage from "./recognition/TestPage";
import VehiclesPage from "./recognition/VehiclesPage";
import SceneBuilderPage from "./scene-builder/SceneBuilderPage";
import RelationshipExplorerPage from "./relationships/ExplorerPage";
import RelationshipRulesPage from "./relationships/RulesPage";
import RelationshipSearchPage from "./relationships/SearchPage";
import RelationshipSettingsPage from "./relationships/SettingsPage";
import RelationshipTimelinePage from "./relationships/TimelinePage";
import GraphPage from "./locations/GraphPage";
import JourneyPage from "./locations/JourneyPage";
import SiteViewPage from "./locations/SiteViewPage";
import TopologyPage from "./locations/TopologyPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomeRedirect />} />
        <Route path="setup" element={<SetupPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectPage />} />
        <Route path="projects/:projectId/:tab" element={<ProjectPage />} />
        <Route path="scene/:cameraId" element={<SceneBuilderPage />} />
        <Route path="live" element={<LivePage />} />
        <Route path="experiments" element={<ExperimentsPage />} />
        <Route path="experiments/:experimentId" element={<ExperimentPage />} />
        <Route path="data" element={<DataPage />} />
        <Route path="analysis" element={<AnalysisPage />} />
        <Route path="analysis/runs/:runId" element={<RunAnalysisPage />} />
        <Route path="review/:runId" element={<ReviewPage />} />
        <Route path="anomalies" element={<AnomaliesPage />} />
        <Route path="anomalies/assistant" element={<AnomalyAssistantPage />} />
        <Route path="relationships" element={<RelationshipExplorerPage />} />
        <Route path="relationships/timeline" element={<RelationshipTimelinePage />} />
        <Route path="relationships/search" element={<RelationshipSearchPage />} />
        <Route path="relationships/rules" element={<RelationshipRulesPage />} />
        <Route path="relationships/settings" element={<RelationshipSettingsPage />} />
        <Route path="relationships/graph" element={<GraphPage />} />
        <Route path="relationships/journeys" element={<JourneyPage />} />
        <Route path="locations" element={<Navigate to="/locations/site" replace />} />
        <Route path="locations/site" element={<SiteViewPage />} />
        <Route path="locations/topology" element={<TopologyPage />} />
        <Route path="cameras" element={<CamerasPage />} />
        <Route path="cameras/:cameraId" element={<CamerasPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="hardware" element={<HardwarePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="recognition" element={<Navigate to="/recognition/settings" replace />} />
        <Route path="recognition/people" element={<PeoplePage />} />
        <Route path="recognition/vehicles" element={<VehiclesPage />} />
        <Route path="recognition/events" element={<RecognitionEventsPage />} />
        <Route path="recognition/test" element={<RecognitionTestPage />} />
        <Route path="recognition/settings" element={<RecognitionSettingsPage />} />
        <Route path="guides" element={<GuidesPage />} />
        <Route path="guides/:slug" element={<GuidePage />} />
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Route>
    </Routes>
  );
}
