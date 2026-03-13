import React from 'react';
import ReactDOM from 'react-dom/client';
import { Toaster } from 'sonner';
import Dashboard from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <Dashboard />
        <Toaster theme="dark" position="bottom-right" richColors />
    </React.StrictMode>,
);
