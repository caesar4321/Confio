import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, gql } from '@apollo/client';
import { Helmet } from 'react-helmet';
import './Verification.css';

const VERIFY_TRANSACTION = gql`
  query VerifyTransaction($transactionHash: String!) {
    verifyTransaction(transactionHash: $transactionHash) {
        isValid
        status
        transactionHash
        amount
        currency
        timestamp
        senderName
        recipientNameMasked
        recipientPhoneMasked
        verificationMessage
        transactionType
        metadata
    }
  }
`;

const TransactionVerificationPage = () => {
    const { hash } = useParams();
    const { loading, error, data } = useQuery(VERIFY_TRANSACTION, {
        variables: { transactionHash: hash },
        skip: !hash,
        fetchPolicy: 'network-only'
    });

    const [formattedDate, setFormattedDate] = useState('');
    const [parsedMetadata, setParsedMetadata] = useState({});

    useEffect(() => {
        if (data?.verifyTransaction?.timestamp) {
            const d = new Date(data.verifyTransaction.timestamp);
            setFormattedDate(d.toLocaleDateString('es-AR', {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            }));
        }
        if (data?.verifyTransaction?.metadata) {
            try {
                setParsedMetadata(JSON.parse(data.verifyTransaction.metadata));
            } catch (e) {
                console.error('Error parsing metadata', e);
            }
        }
    }, [data]);

    if (loading) return (
        <div className="verification-container loading">
            <div className="spinner"></div>
            <p className="loading-text">Verificando transacción...</p>
        </div>
    );

    const result = data?.verifyTransaction;
    const isValid = result?.isValid;
    const isRevoked = result?.status === 'REVOKED';

    // Helper to get labels based on type
    const getLabels = (type) => {
        switch (type) {
            case 'PAYROLL':
                return {
                    title: 'Comprobante de Nómina',
                    sender: 'Empresa',
                    recipient: 'Empleado',
                    message: 'Pago de nómina verificado'
                };
            case 'PAYMENT':
                return {
                    title: 'Comprobante de Pago',
                    sender: 'Pagador',
                    recipient: 'Comercio',
                    message: 'Pago a comercio verificado'
                };
            case 'TRANSFER':
            default:
                return {
                    title: 'Comprobante de Transacción',
                    sender: 'Remitente',
                    recipient: 'Destinatario',
                    message: 'Transacción verificada'
                };
        }
    };

    const labels = getLabels(result?.transactionType);

    // Fallback for invalid hash or error
    if (!result || error) {
        return (
            <div className="verification-container invalid">
                <Helmet>
                    <title>Verificación Fallida | Confío</title>
                </Helmet>
                <div className="verification-card">
                    <div className="status-icon-circle error">
                        <i className="fas fa-times"></i>
                    </div>
                    <h1>No encontrada</h1>
                    <p className="verification-message">
                        No pudimos encontrar esta transacción en nuestros registros.
                        El código puede ser incorrecto o la transacción no existe.
                    </p>
                    <div className="hash-box">
                        <div className="hash-label">Código consultado:</div>
                        <div className="hash-value">{hash}</div>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className={`verification-container ${isValid ? 'valid' : 'revoked'}`}>
            <Helmet>
                <title>{isValid ? `${labels.title} Verificado` : 'Transacción Revocada'} | Confío</title>
                <meta name="theme-color" content={isValid ? '#10B981' : '#EF4444'} />
            </Helmet>

            <div className="verification-card">
                <div className="security-banner-web">
                    <i className="fas fa-lock"></i> confio.lat <i className="fas fa-check-circle"></i>
                </div>

                <div className="status-section">
                    <div className={`status-icon-circle ${isValid ? 'success' : 'revoked'}`}>
                        <i className={`fas ${isValid ? 'fa-check' : 'fa-exclamation-triangle'}`}></i>
                    </div>
                    <h2 className={`status-title ${isValid ? 'text-success' : 'text-danger'}`}>
                        {isValid ? 'Comprobante Validado' : (isRevoked ? 'Transacción Revocada' : 'Transacción Inválida')}
                    </h2>
                    <p className="verification-subtext">{result.verificationMessage || labels.message}</p>
                </div>

                {isValid && (
                    <div className="details-card">
                        <div className="amount-section">
                            <span className="amount-label">Monto Total</span>
                            <div className="amount-display">
                                {result.amount} <small>{result.currency === 'CUSD' ? 'cUSD' : result.currency}</small>
                            </div>
                            <div className="date-display">{formattedDate}</div>
                        </div>

                        <div className="info-row">
                            <div className="info-col">
                                <label>{labels.sender}</label>
                                <div className="info-value strong">{result.senderName}</div>
                            </div>
                            <div className="info-col text-right">
                                <label>{labels.recipient}</label>
                                <div className="info-value masked">
                                    {result.recipientNameMasked}
                                    {result.recipientPhoneMasked && <span className="phone-sub">{result.recipientPhoneMasked}</span>}
                                </div>
                            </div>
                        </div>

                        {(parsedMetadata?.referenceId || parsedMetadata?.memo) && <div className="divider"></div>}

                        {parsedMetadata?.referenceId && (
                            <div className="info-row single">
                                <label>Referencia</label>
                                <div className="info-value">{parsedMetadata.referenceId}</div>
                            </div>
                        )}

                        {parsedMetadata?.memo && (
                            <div className="info-row single">
                                <label>Concepto</label>
                                <div className="info-value">{parsedMetadata.memo}</div>
                            </div>
                        )}

                        <div className="divider"></div>



                        <div className="certification-badge">
                            <i className="fas fa-shield-alt"></i>
                            <span>Confío certifica la autenticidad de este comprobante.</span>
                        </div>
                    </div>
                )}

                <div className="verification-footer">
                    <p>Confío &copy; {new Date().getFullYear()}</p>
                </div>
            </div>
        </div>
    );
};

export default TransactionVerificationPage;
