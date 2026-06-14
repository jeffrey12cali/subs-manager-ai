import { Route, Routes, Link, NavLink } from "react-router-dom";
import Library from "./pages/Library";
import Movie from "./pages/Movie";
import Jobs from "./pages/Jobs";

function Nav() {
  const base = "px-3 py-2 text-sm rounded hover:bg-neutral-800 transition-colors";
  const active = `${base} text-white`;
  const inactive = `${base} text-neutral-400`;
  return (
    <nav className="flex items-center gap-1 border-b border-neutral-800 px-4 py-2">
      <span className="mr-4 font-bold text-neutral-200">Subs Manager</span>
      <NavLink to="/" end className={({ isActive }) => (isActive ? active : inactive)}>
        Library
      </NavLink>
      <NavLink to="/jobs" className={({ isActive }) => (isActive ? active : inactive)}>
        Jobs
      </NavLink>
    </nav>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <Nav />
      <Routes>
        <Route path="/" element={<Library />} />
        <Route path="/movies/:id" element={<Movie />} />
        <Route path="/jobs" element={<Jobs />} />
        <Route
          path="*"
          element={
            <div className="p-6 text-neutral-500">
              Page not found. <Link to="/" className="underline">Back to library</Link>
            </div>
          }
        />
      </Routes>
    </div>
  );
}
