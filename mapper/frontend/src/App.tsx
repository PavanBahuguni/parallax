import { Routes, Route } from 'react-router-dom'
import Navigation from './components/Navigation'
import DashboardPage from './pages/DashboardPage'
import TaskDetailPage from './pages/TaskDetailPage'
import ExecutionsPage from './pages/ExecutionsPage'
import './App.css'

function App() {
  return (
    <div className="app">
      <Navigation />
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
        <Route path="/executions" element={<ExecutionsPage />} />
      </Routes>
    </div>
  )
}

export default App
