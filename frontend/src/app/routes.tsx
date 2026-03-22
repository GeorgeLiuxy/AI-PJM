import { createBrowserRouter } from "react-router";
import Root from "./Root";
import HomePage from "./pages/HomePage";
import UnifiedInputPage from "./pages/UnifiedInputPage";
import TaskProcessorPage from "./pages/TaskProcessorPage";
import ImpactAnalysisPage from "./pages/ImpactAnalysisPage";
import ResultsWorkbenchPage from "./pages/ResultsWorkbenchPage";
import ItemDetailPage from "./pages/ItemDetailPage";

export const router = createBrowserRouter([
  {
    path: "/",
    Component: Root,
    children: [
      { index: true, Component: HomePage },
      { path: "input", Component: UnifiedInputPage },
      { path: "process", Component: TaskProcessorPage },
      { path: "impact/:analysisId", Component: ImpactAnalysisPage },
      { path: "impact", Component: ImpactAnalysisPage },
      { path: "results/:itemId", Component: ResultsWorkbenchPage },
      { path: "results", Component: ResultsWorkbenchPage },
      { path: "items/:id", Component: ItemDetailPage },
    ],
  },
]);