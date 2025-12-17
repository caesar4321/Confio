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
            <p>Verificando transacción...</p>
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
                    sender: 'Empresa (Remitente)',
                    recipient: 'Empleado (Destinatario)',
                    message: 'Pago de nómina verificado'
                };
            case 'PAYMENT':
                return {
                    title: 'Comprobante de Pago',
                    sender: 'Cliente (Pagador)',
                    recipient: 'Comercio (Receptor)',
                    message: 'Pago a comercio verificado'
                };
            case 'TRANSFER':
                return {
                    title: 'Comprobante de Transferencia',
                    sender: 'Remitente',
                    recipient: 'Destinatario',
                    message: 'Transferencia verificada'
                };
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
                <div className="security-banner">
                    <span className="secure-icon">🔒</span>
                    Estás en <span className="domain-highlight">confio.lat</span>
                    <span className="secure-check">✓</span>
                </div>
                <div className="verification-card">
                    <div className="status-icon invalid">❌</div>
                    <h1>Verificación Fallida</h1>
                    <p className="verification-message">
                        No pudimos encontrar esta transacción en nuestros registros.
                        El código puede ser incorrecto o la transacción no existe.
                    </p>
                    <div className="hash-display">
                        <span>Hash consultado:</span>
                        <code>{hash}</code>
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

            <div className="security-banner">
                <span className="secure-icon">🔒</span>
                Estás en <span className="domain-highlight">confio.lat</span>
                <span className="secure-check">✓</span>
            </div>

            <div className="verification-card">
                <div className={`status-icon ${isValid ? 'valid' : 'revoked'}`}>
                    {isValid ? '✅' : (isRevoked ? '⚠️' : '❌')}
                </div>

                <div className="verification-header">
                    <span className="verification-type-badge">{labels.title}</span>
                </div>

                <h1>{isValid ? 'Comprobante Validado' : (isRevoked ? 'Transacción Revocada' : 'Transacción Inválida')}</h1>
                {isValid && (
                    <p className="certification-text">
                        Confío certifica la coincidencia de los datos del comprobante con la transacción registrada en Algorand.
                    </p>
                )}

                <p className="verification-message">{result.verificationMessage || labels.message}</p>

                {isValid && (
                    <div className="details-grid">
                        <div className="detail-item full-width">
                            <label>Monto</label>
                            <div className="amount-value">
                                {result.amount} <small>{result.currency}</small>
                            </div>
                        </div>

                        <div className="detail-item">
                            <label>Fecha</label>
                            <div>{formattedDate}</div>
                        </div>

                        <div className="detail-item">
                            <label>{labels.sender}</label>
                            <div className="business-name">{result.senderName}</div>
                        </div>

                        <div className="detail-item">
                            <label>{labels.recipient}</label>
                            <div className="masked-data" title="Datos parcialmente ocultos por privacidad">
                                {result.recipientNameMasked}
                                {result.recipientPhoneMasked && <small className="phone-sub">{result.recipientPhoneMasked}</small>}
                            </div>
                        </div>

                        {/* Extra metadata fields if available */}
                        {parsedMetadata && parsedMetadata.referenceId && (
                            <div className="detail-item">
                                <label>Referencia</label>
                                <div>{parsedMetadata.referenceId}</div>
                            </div>
                        )}

                        {parsedMetadata && parsedMetadata.memo && (
                            <div className="detail-item full-width">
                                <label>Concepto</label>
                                <div>{parsedMetadata.memo}</div>
                            </div>
                        )}

                        <div className="detail-item full-width">
                            <label>Hash de Transacción (Blockchain)</label>
                            <div className="hash-container">
                                <a
                                    href={`https://explorer.perawallet.app/tx/${result.transactionHash}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="hash-link"
                                    title="Ver en explorador de bloques"
                                >
                                    <code>{result.transactionHash}</code>
                                </a>
                                <a
                                    href={`https://explorer.perawallet.app/tx/${result.transactionHash}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="explorer-link"
                                >
                                    Ver en AlgoExplorer ↗
                                </a>
                            </div>
                        </div>
                    </div>
                )}

                <div className="verification-footer">
                    <p>Confío | Prueba de Transacción</p>
                </div>
            </div>
        </div>
    );
};

export default TransactionVerificationPage;
