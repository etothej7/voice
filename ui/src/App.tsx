import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from '@/layouts/app-layout';
import { CallDetailPage } from '@/pages/call-detail-page';
import { RepDetailPage } from '@/pages/rep-detail-page';
import { TeamPage } from '@/pages/team-page';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<TeamPage />} />
          <Route path="/reps/:repSlug" element={<RepDetailPage />} />
          <Route path="/calls/:callSlug" element={<CallDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
