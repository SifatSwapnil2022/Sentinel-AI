import { createBrowserRouter, redirect } from "react-router";
import { NotFound, RouteError } from "../pages/NotFound";
import { AppShell } from "./AppShell";

// Pages load on first visit, so the landing page doesn't ship the dashboard's code.
// The landing page stands alone; every dashboard page shares the shell with its sidebar.
export const routes = [
  {
    path: "/",
    errorElement: <RouteError />,
    // Shown for the moment a page's code is still loading on first visit.
    hydrateFallbackElement: <p className="visually-hidden">Loading</p>,
    children: [
      {
        index: true,
        lazy: () => import("../pages/LandingPage").then((m) => ({ Component: m.LandingPage })),
      },
      {
        element: <AppShell />,
        children: [
          {
            path: "overview",
            lazy: () =>
              import("../pages/overview/OverviewPage").then((m) => ({ Component: m.OverviewPage })),
          },
          {
            path: "models",
            lazy: () => import("../pages/models/ModelsPage").then((m) => ({ Component: m.ModelsPage })),
          },
          {
            path: "models/:modelId",
            lazy: () => import("../pages/model/ModelPage").then((m) => ({ Component: m.ModelPage })),
          },
          {
            // Old address of the inputs page, kept so shared links still land in the right place.
            path: "models/:modelId/inputs",
            loader: ({ params }: { params: { modelId?: string } }) =>
              redirect(`/models/${params.modelId ?? ""}?tab=inputs`),
          },
          {
            path: "incidents",
            lazy: () =>
              import("../pages/incidents/IncidentsPage").then((m) => ({ Component: m.IncidentsPage })),
          },
          {
            path: "incidents/:incidentId",
            lazy: () =>
              import("../pages/incident/IncidentPage").then((m) => ({ Component: m.IncidentPage })),
          },
          {
            path: "explore",
            lazy: () => import("../pages/explore/ExplorePage").then((m) => ({ Component: m.ExplorePage })),
          },
          {
            path: "reports",
            lazy: () => import("../pages/reports/ReportsPage").then((m) => ({ Component: m.ReportsPage })),
          },
          { path: "*", element: <NotFound /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
