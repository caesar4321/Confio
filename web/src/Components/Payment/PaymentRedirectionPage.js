import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, gql } from '@apollo/client';
import { Helmet } from 'react-helmet';
import { QRCodeCanvas } from 'qrcode.react';
import '../Verification/Verification.css';

const GET_INVOICE_PUBLIC = gql`
  query GetPublicInvoice($id: String!) {
    resolveInvoice(invoiceId: $id) {
      internalId
      amount
      currency
      status
      description
      createdByUser {
        firstName
        lastName
      }
    }
  }
`;

const PaymentRedirectionPage = () => {
    const { id } = useParams();
    const { loading, error, data } = useQuery(GET_INVOICE_PUBLIC, {
        variables: { id },
        skip: !id,
        fetchPolicy: 'network-only' // Ensure fresh status
    });

    useEffect(() => {
        // Attempt deep link redirection immediately on mount for mobile
        if (id) {
            const appLink = `confio://pay/${id}`;
            // Only redirect if not desktop? (Simple heuristic)
            if (/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)) {
                window.location.href = appLink;
            }
        }
    }, [id]);

    const invoice = data?.resolveInvoice;

    // Loading State
    if (loading) {
        return (
            <div className="verification-container loading">
                <div className="spinner"></div>
                <p className="loading-text">Cargando pago...</p>
            </div>
        );
    }

    // Error or Not Found State
    if (error || !invoice) {
        return (
            <div className="verification-container invalid">
                <Helmet><title>Error | Confío</title></Helmet>
                <div className="verification-card">
                    <div className="status-icon-circle error"><i className="fas fa-times"></i></div>
                    <h1>No encontrado</h1>
                    <p className="verification-message">El pago que buscas no existe o ha expirado.</p>
                </div>
            </div>
        );
    }

    const { amount, currency, status, description, createdByUser } = invoice;
    const isPaid = status === 'PAID';
    const merchantName = createdByUser ? `${createdByUser.firstName} ${createdByUser.lastName}` : 'Comercio Confío';
    const qrValue = `confio://pay/${invoice.internalId}`;

    return (
        <div className="verification-container">
            <Helmet>
                <title>Pagar ${amount} | Confío</title>
                <meta name="theme-color" content="#10B981" />
            </Helmet>

            <div className="verification-card" style={{ textAlign: 'center' }}>
                <div className="security-banner-web">
                    <i className="fas fa-lock"></i> confio.lat <i className="fas fa-check-circle"></i>
                </div>

                {isPaid ? (
                    <div className="status-section">
                        <div className="status-icon-circle success"><i className="fas fa-check"></i></div>
                        <h2 className="status-title text-success">¡Pago Exitoso!</h2>
                        <p className="verification-subtext">Este pago ya ha sido completado.</p>
                    </div>
                ) : (
                    <>
                        <div style={{ marginBottom: '24px' }}>
                            <p style={{ fontSize: '14px', color: '#6B7280', marginBottom: '4px' }}>Estás pagando a</p>
                            <h2 style={{ fontSize: '20px', fontWeight: '700', margin: '0 0 8px 0' }}>{merchantName}</h2>
                            <div className="amount-display" style={{ fontSize: '36px' }}>
                                {amount} <small>{currency}</small>
                            </div>
                            {description && (
                                <p style={{ fontSize: '14px', color: '#374151', marginTop: '8px', fontStyle: 'italic' }}>
                                    "{description}"
                                </p>
                            )}
                        </div>

                        <div style={{
                            background: 'white',
                            padding: '20px',
                            borderRadius: '16px',
                            border: '1px solid #E5E7EB',
                            display: 'inline-block',
                            marginBottom: '24px'
                        }}>
                            <QRCodeCanvas value={qrValue} size={200} level={"H"} includeMargin={false} />
                            <p style={{ fontSize: '12px', color: '#6B7280', marginTop: '12px', marginBottom: 0 }}>
                                Escanea con tu cámara o App Confío
                            </p>
                        </div>
                    </>
                )}

                {!isPaid && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        <a
                            href={qrValue}
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
                            Abrir App para Pagar
                        </a>
                    </div>
                )}

                <div className="verification-footer">
                    <p>Confío &copy; {new Date().getFullYear()}</p>
                </div>
            </div>
        </div>
    );
};

export default PaymentRedirectionPage;
