import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { Helmet } from 'react-helmet';
import '../Verification/Verification.css';

const PaymentRedirectionPage = () => {
    const { id } = useParams();

    useEffect(() => {
        // Attempt deep link redirection immediately
        if (id) {
            const appLink = `confio://pay/${id}`;
            window.location.href = appLink;

            // Optional: fallback logic if needed
        }
    }, [id]);

    return (
        <div className="verification-container">
            <Helmet>
                <title>Completar Pago | Confío</title>
                <meta name="theme-color" content="#10B981" />
            </Helmet>

            <div className="verification-card" style={{ textAlign: 'center' }}>
                <div className="security-banner-web">
                    <i className="fas fa-lock"></i> confio.lat <i className="fas fa-check-circle"></i>
                </div>

                <div className="status-icon-circle success">
                    <i className="fas fa-mobile-alt"></i>
                </div>

                <h1 className="status-title text-success">
                    Abriendo Confío...
                </h1>

                <p className="verification-subtext" style={{ marginBottom: '24px' }}>
                    Si la app no se abre automáticamente, usa los botones de abajo.
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <a
                        href={`confio://pay/${id}`}
                        className="btn-primary"
                        style={{
                            background: '#10B981',
                            color: 'white',
                            padding: '12px 20px',
                            borderRadius: '12px',
                            textDecoration: 'none',
                            fontWeight: '600',
                            display: 'block'
                        }}
                    >
                        Abrir App
                    </a>

                    <div style={{ marginTop: '12px', fontSize: '14px', color: '#6B7280' }}>
                        ¿No tienes la app?
                    </div>

                    <div style={{ display: 'flex', gap: '10px', justifyContent: 'center' }}>
                        <a href="https://play.google.com/store/apps/details?id=com.Confio.Confio" target="_blank" rel="noopener noreferrer">
                            <img src="https://upload.wikimedia.org/wikipedia/commons/7/78/Google_Play_Store_badge_EN.svg" alt="Google Play" style={{ height: '40px' }} />
                        </a>
                        <a href="https://apps.apple.com/app/id6472662314" target="_blank" rel="noopener noreferrer">
                            <img src="https://upload.wikimedia.org/wikipedia/commons/3/3c/Download_on_the_App_Store_Badge.svg" alt="App Store" style={{ height: '40px' }} />
                        </a>
                    </div>
                </div>

                <div className="verification-footer">
                    <p>Confío &copy; {new Date().getFullYear()}</p>
                </div>
            </div>
        </div>
    );
};

export default PaymentRedirectionPage;
