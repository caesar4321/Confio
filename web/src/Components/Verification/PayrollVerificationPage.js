import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, gql } from '@apollo/client';
import { Helmet } from 'react-helmet';
import './Verification.css';

const VERIFY_PAYROLL_TRANSACTION = gql`
  query VerifyPayrollTransaction($transactionHash: String!) {
    verifyPayrollTransaction(transactionHash: $transactionHash) {
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
    }
  }
`;

const PayrollVerificationPage = () => {
    const { hash } = useParams();
    const { loading, error, data } = useQuery(VERIFY_PAYROLL_TRANSACTION, {
        variables: { transactionHash: hash },
        skip: !hash,
    });

    const [formattedDate, setFormattedDate] = useState('');

    useEffect(() => {
        if (data?.verifyPayrollTransaction?.timestamp) {
            const d = new Date(data.verifyPayrollTransaction.timestamp);
            setFormattedDate(d.toLocaleDateString('es-AR', {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            }));
        }
    }, [data]);

    if (loading) return (
        <div className="verification-container loading">
            <div className="spinner"></div>
            <p>Verificando transacción...</p>
        </div>
    );

    const result = data?.verifyPayrollTransaction;
    const isValid = result?.isValid;
    const isRevoked = result?.status === 'REVOKED';

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
                <title>{isValid ? 'Transacción Verificada' : 'Transacción Revocada'} | Confío</title>
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

                <h1>{isValid ? 'Comprobante Validado' : (isRevoked ? 'Transacción Revocada' : 'Transacción Inválida')}</h1>
                {isValid && (
                    <p className="certification-text">
                        Confío certifica la coincidencia de los datos del comprobante con la transacción registrada en Algorand.
                    </p>
                )}

                <p className="verification-message">{result.verificationMessage}</p>

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
                            <label>Empresa (Remitente)</label>
                            <div className="business-name">{result.senderName}</div>
                        </div>

                        <div className="detail-item">
                            <label>Empleado (Destinatario)</label>
                            <div className="masked-data" title="Datos parcialmente ocultos por privacidad">
                                {result.recipientNameMasked}
                                {result.recipientPhoneMasked && <small className="phone-sub">{result.recipientPhoneMasked}</small>}
                            </div>
                        </div>

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

export default PayrollVerificationPage;
