import { createBrowserRouter } from "react-router";
import { NotFound, RouteError } from "../pages/NotFound";
import { AppShell } from "./AppShell";

// Pages load on first visit, so the overview doesn't ship the incident page's code.
export const routes = [
  {
    path: "/",
    element: <AppShell />,
    errorElement: <RouteError />,
    // Shown for the moment a page's code is still loading on first visit.
    hydrateFallbackElement: <p className="visually-hidden">Loading</p>,
    children: [
      {
        index: true,
        lazy: () => import("../pages/FleetPage").then((m) => ({ Component: m.FleetPage })),
      },
      {
        path: "models/:modelId",
        lazy: () => import("../pages/ModelPage").then((m) => ({ Component: m.ModelPage })),
      },
      {
        path: "models/:modelId/inputs",
        lazy: () =>
          import("../pages/ModelInputsPage").then((m) => ({ Component: m.ModelInputsPage })),
      },
      {
        path: "incidents",
        lazy: () => import("../pages/IncidentsPage").then((m) => ({ Component: m.IncidentsPage })),
      },
      {
        path: "incidents/:incidentId",
        lazy: () => import("../pages/IncidentPage").then((m) => ({ Component: m.IncidentPage })),
      },
      { path: "*", element: <NotFound /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
