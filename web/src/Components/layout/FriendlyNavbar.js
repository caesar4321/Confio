import React from 'react';

const FriendlyNavbar = () => {
  return (
    <nav style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      background: 'white',
      boxShadow: '0 2px 10px rgba(0,0,0,0.08)',
      padding: '1rem 2rem',
      zIndex: 1000
    }}>
      <div style={{
        maxWidth: '1400px',
        margin: '0 auto',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center'
      }}>
        <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#34d399' }}>
          💚 Confío
        </div>
        <button style={{
          background: 'linear-gradient(135deg, #34d399, #10b981)',
          color: 'white',
          border: 'none',
          padding: '10px 24px',
          borderRadius: '12px',
          fontWeight: '600',
          cursor: 'pointer'
        }}>
          Descargar App
        </button>
      </div>
    </nav>
  );
};

export default FriendlyNavbar;