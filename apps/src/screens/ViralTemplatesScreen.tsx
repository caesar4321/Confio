import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Linking,
  Share,
  Alert,
  Clipboard,
  Modal,
} from 'react-native';
import { NavigationProp } from '@react-navigation/native';
import Svg, { Defs, LinearGradient, Stop, Rect } from 'react-native-svg';
import Icon from 'react-native-vector-icons/Feather';

interface ViralTemplatesScreenProps {
  navigation: NavigationProp<any>;
}

interface VideoTemplate {
  id: string;
  title: string;
  description: string;
  script: string;
  hashtags: string;
  tips: string[];
  difficulty: 'fácil' | 'medio' | 'avanzado';
  estimatedViews: string;
  icon: string;
}

const videoTemplates: VideoTemplate[] = [
  {
    id: '1',
    title: 'Mi Primera Transacción',
    description: 'Muestra lo fácil que es enviar dólares con Confío',
    script: '🎬 GUIÓN:\n\n1. Abre con problema: "¿Cansado de las comisiones bancarias?"\n2. Muestra la app: "Mira lo que descubrí"\n3. Graba el proceso: Envía $1 a un amigo\n4. Reacción: "¡Llegó en segundos!"\n5. Cierre: "Descarga Confío y empieza a ahorrar"',
    hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
    tips: [
      'Usa música trending de TikTok',
      'Mantén el video bajo 30 segundos',
      'Muestra números reales (sin datos sensibles)',
      'Graba la reacción de tu amigo al recibir'
    ],
    difficulty: 'fácil',
    estimatedViews: '1K-5K',
    icon: '💸'
  },
  {
    id: '2',
    title: 'Confío vs Bancos',
    description: 'Compara las comisiones y tiempos de espera',
    script: '🎬 GUIÓN:\n\n1. Split screen: Banco vs Confío\n2. Banco: "3 días de espera, $25 de comisión"\n3. Confío: "Instantáneo, sin comisiones"\n4. Muestra prueba real: cronómetro\n5. Final: "¿Qué prefieres?"',
    hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
    tips: [
      'Usa efectos de comparación (split screen)',
      'Incluye capturas reales de fees bancarios',
      'Añade stickers de reloj y dinero',
      'Termina con CTA claro'
    ],
    difficulty: 'medio',
    estimatedViews: '5K-20K',
    icon: '🏦'
  },
  {
    id: '3',
    title: 'Story Time: Mi Historia',
    description: 'Cuenta tu experiencia personal con remesas',
    script: '🎬 GUIÓN:\n\n1. Hook: "Story time de cómo Confío me salvó"\n2. Problema: Necesitaba enviar dinero urgente\n3. Frustración: Bancos cerrados/comisiones altas\n4. Solución: Descubrí Confío\n5. Final feliz: "Ahora mi familia recibe al instante"',
    hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
    tips: [
      'Sé auténtico y emocional',
      'Usa texto en pantalla para énfasis',
      'Incluye fotos/videos de tu familia',
      'La vulnerabilidad conecta'
    ],
    difficulty: 'fácil',
    estimatedViews: '10K-50K',
    icon: '📖'
  },
  {
    id: '4',
    title: 'Tutorial P2P Exchange',
    description: 'Enseña cómo comprar/vender dólares',
    script: '🎬 GUIÓN:\n\n1. "POV: Necesitas dólares YA"\n2. Abre P2P Exchange\n3. Muestra ofertas disponibles\n4. Proceso paso a paso (rápido)\n5. "En 5 minutos tienes tus dólares"',
    hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
    tips: [
      'Usa POV para engagement',
      'Acelera partes aburridas',
      'Destaca la seguridad',
      'Muestra notificaciones de éxito'
    ],
    difficulty: 'medio',
    estimatedViews: '3K-15K',
    icon: '💱'
  },
  {
    id: '5',
    title: 'Reto de Velocidad',
    description: 'Cronometra una transacción en tiempo real',
    script: '🎬 GUIÓN:\n\n1. "¿Cuánto tarda una transferencia con Confío?"\n2. Inicia cronómetro\n3. Envía dinero en vivo\n4. Muestra confirmación\n5. Para cronómetro: "X segundos!"',
    hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
    tips: [
      'Hazlo en una sola toma',
      'Pide a amigo que grabe recepción',
      'Usa efectos de velocidad',
      'Compara con "3-5 días bancarios"'
    ],
    difficulty: 'fácil',
    estimatedViews: '5K-25K',
    icon: '⏱️'
  },
  {
    id: '6',
    title: 'Reacción de Padres',
    description: 'Graba cuando tus padres usan Confío',
    script: '🎬 GUIÓN:\n\n1. "Le enseñé Confío a mi mamá/papá"\n2. Graba su reacción al ver la velocidad\n3. Sus comentarios sobre las comisiones\n4. El momento "wow"\n5. "Ahora toda la familia usa Confío"',
    hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
    tips: [
      'Las reacciones genuinas son oro',
      'Subtitula si hablan bajo',
      'Captura expresiones faciales',
      'Momento multi-generacional vende'
    ],
    difficulty: 'medio',
    estimatedViews: '20K-100K',
    icon: '👨‍👩‍👧'
  },
  {
    id: '7',
    title: 'Sketch Cómico',
    description: 'Parodia las colas del banco',
    script: '🎬 GUIÓN:\n\n1. Actuación: En cola del banco (acelera tiempo)\n2. "3 horas después..."\n3. "Necesita 5 formularios más"\n4. Corte a: Usando Confío desde el sofá\n5. "Trabajo inteligente, no duro"',
    hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
    tips: [
      'Exagera para efecto cómico',
      'Usa música de comedia',
      'Contraste visual fuerte',
      'Relatable = viral'
    ],
    difficulty: 'avanzado',
    estimatedViews: '10K-200K',
    icon: '😂'
  },
  {
    id: '8',
    title: 'Testimonio Emprendedor',
    description: 'Cómo Confío ayuda tu negocio',
    script: '🎬 GUIÓN:\n\n1. "Soy emprendedor y Confío cambió mi negocio"\n2. Muestra pagos a proveedores\n3. Cobros de clientes internacionales\n4. "Sin comisiones = más ganancias"\n5. "Únete a la revolución financiera"',
    hashtags: '#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital',
    tips: [
      'Muestra casos reales',
      'Incluye números (sin revelar todo)',
      'Aspecto profesional',
      'Inspira a otros emprendedores'
    ],
    difficulty: 'medio',
    estimatedViews: '5K-30K',
    icon: '💼'
  }
];

export const ViralTemplatesScreen: React.FC<ViralTemplatesScreenProps> = ({ navigation }) => {
  const [selectedTemplate, setSelectedTemplate] = useState<VideoTemplate | null>(null);

  const copyToClipboard = (text: string) => {
    Clipboard.setString(text);
    Alert.alert('¡Copiado!', 'El texto ha sido copiado al portapapeles');
  };

  const shareTemplate = async (template: VideoTemplate) => {
    try {
      await Share.share({
        message: `🎬 Idea para TikTok: ${template.title}\n\n${template.script}\n\n${template.hashtags}\n\n📱 Descarga Confío: confio.lat`,
      });
    } catch (error) {
      Alert.alert('Error', 'No se pudo compartir');
    }
  };

  const getDifficultyColor = (difficulty: string) => {
    switch (difficulty) {
      case 'fácil': return '#10B981';
      case 'medio': return '#F59E0B';
      case 'avanzado': return '#EF4444';
      default: return '#6B7280';
    }
  };

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <TouchableOpacity 
          onPress={() => navigation.goBack()} 
          style={styles.backButton}
        >
          <Icon name="arrow-left" size={24} color="#fff" />
        </TouchableOpacity>
        <View style={styles.headerContent}>
          <Text style={styles.headerTitle}>Ideas para TikTok</Text>
        </View>
        <View style={styles.headerSpacer} />
      </View>

      <View style={styles.tipsContainer}>
        <Text style={styles.sectionTitle}>💡 Tips Generales</Text>
        <View style={styles.tipCard}>
          <Text style={styles.tipText}>• Graba en vertical (9:16)</Text>
          <Text style={styles.tipText}>• Primeros 3 segundos son clave</Text>
          <Text style={styles.tipText}>• Usa trends de música actual</Text>
          <Text style={styles.tipText}>• Interactúa con comentarios</Text>
          <Text style={styles.tipText}>• Publica entre 6-10pm</Text>
          <Text style={styles.tipText}>• Consistencia > Perfección</Text>
        </View>
      </View>

      <View style={styles.templatesContainer}>
        <Text style={styles.sectionTitle}>📱 Plantillas de Video</Text>
        
        {videoTemplates.map((template) => (
          <TouchableOpacity
            key={template.id}
            style={styles.templateCard}
            onPress={() => setSelectedTemplate(template)}
            activeOpacity={0.7}
          >
            <View style={styles.templateHeader}>
              <Text style={styles.templateIcon}>{template.icon}</Text>
              <View style={styles.templateInfo}>
                <Text style={styles.templateTitle}>{template.title}</Text>
                <Text style={styles.templateDescription}>{template.description}</Text>
              </View>
            </View>
            
            <View style={styles.templateMeta}>
              <View style={[
                styles.difficultyBadge,
                { backgroundColor: getDifficultyColor(template.difficulty) }
              ]}>
                <Text style={styles.difficultyText}>{template.difficulty}</Text>
              </View>
              <Text style={styles.viewsEstimate}>👁️ {template.estimatedViews}</Text>
            </View>
          </TouchableOpacity>
        ))}
      </View>

      <View style={styles.hashtagsContainer}>
        <Text style={styles.sectionTitle}>📌 Hashtags Oficiales</Text>
        <TouchableOpacity 
          style={styles.hashtagCard}
          onPress={() => copyToClipboard('#Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital')}
        >
          <Text style={styles.hashtagText}>
            #Confio #RetoConfio #LogroConfio #AppDeDolares #DolarDigital
          </Text>
          <Text style={styles.copyHint}>Toca para copiar</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.ctaContainer}>
        <TouchableOpacity
          style={styles.ctaButton}
          onPress={() => Linking.openURL('https://www.tiktok.com/upload')}
        >
          <Text style={styles.ctaButtonText}>Subir a TikTok</Text>
        </TouchableOpacity>
      </View>

      {/* Template Detail Modal */}
      <Modal
        visible={!!selectedTemplate}
        transparent={true}
        animationType="slide"
        onRequestClose={() => setSelectedTemplate(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalIcon}>{selectedTemplate?.icon}</Text>
              <Text style={styles.modalTitle}>{selectedTemplate?.title}</Text>
              <TouchableOpacity
                style={styles.closeButton}
                onPress={() => setSelectedTemplate(null)}
              >
                <Text style={styles.closeButtonText}>✕</Text>
              </TouchableOpacity>
            </View>

            <ScrollView 
              style={styles.modalScroll}
              contentContainerStyle={styles.modalScrollContent}
              showsVerticalScrollIndicator={true}
            >
              {selectedTemplate ? (
                <>
                  <Text style={styles.modalSectionTitle}>📝 Guión Completo</Text>
                  <TouchableOpacity
                    style={styles.scriptBox}
                    onPress={() => selectedTemplate && copyToClipboard(selectedTemplate.script)}
                  >
                    <Text style={styles.scriptText}>{selectedTemplate?.script}</Text>
                    <Text style={styles.copyHint}>Toca para copiar</Text>
                  </TouchableOpacity>

                  <Text style={styles.modalSectionTitle}>💡 Tips de Producción</Text>
                  {selectedTemplate?.tips?.map((tip, index) => (
                    <Text key={index} style={styles.tipItem}>• {tip}</Text>
                  ))}

                  <Text style={styles.modalSectionTitle}>#️⃣ Hashtags</Text>
                  <TouchableOpacity
                    style={styles.hashtagBox}
                    onPress={() => selectedTemplate && copyToClipboard(selectedTemplate.hashtags)}
                  >
                    <Text style={styles.hashtagTextModal}>{selectedTemplate?.hashtags}</Text>
                  </TouchableOpacity>

                  <View style={styles.modalActions}>
                    <TouchableOpacity
                      style={styles.shareButton}
                      onPress={() => selectedTemplate && shareTemplate(selectedTemplate)}
                    >
                      <Text style={styles.shareButtonText}>Compartir Idea</Text>
                    </TouchableOpacity>
                    
                    <TouchableOpacity
                      style={styles.createButton}
                      onPress={() => {
                        setSelectedTemplate(null);
                        Linking.openURL('https://www.tiktok.com/upload');
                      }}
                    >
                      <Text style={styles.createButtonText}>Crear Video</Text>
                    </TouchableOpacity>
                  </View>
                </>
              ) : null}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8f9fa',
  },
  header: {
    backgroundColor: '#34d399',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 12,
    paddingBottom: 20,
    paddingHorizontal: 20,
  },
  backButton: {
    padding: 8,
  },
  headerContent: {
    flex: 1,
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: 'white',
  },
  headerSpacer: {
    width: 40,
  },
  tipsContainer: {
    padding: 20,
  },
  sectionTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: '#212529',
    marginBottom: 15,
  },
  tipCard: {
    backgroundColor: 'white',
    padding: 20,
    borderRadius: 15,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.05,
    shadowRadius: 3,
    elevation: 2,
  },
  tipText: {
    fontSize: 16,
    color: '#495057',
    marginBottom: 8,
    lineHeight: 24,
  },
  templatesContainer: {
    padding: 20,
  },
  templateCard: {
    backgroundColor: 'white',
    padding: 20,
    borderRadius: 15,
    marginBottom: 15,
    shadowColor: '#000',
    shadowOffset: {
      width: 0,
      height: 2,
    },
    shadowOpacity: 0.05,
    shadowRadius: 3,
    elevation: 2,
  },
  templateHeader: {
    flexDirection: 'row',
    marginBottom: 15,
  },
  templateIcon: {
    fontSize: 40,
    marginRight: 15,
  },
  templateInfo: {
    flex: 1,
  },
  templateTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#212529',
    marginBottom: 5,
  },
  templateDescription: {
    fontSize: 14,
    color: '#6c757d',
  },
  templateMeta: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  difficultyBadge: {
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
  },
  difficultyText: {
    color: 'white',
    fontSize: 12,
    fontWeight: '600',
  },
  viewsEstimate: {
    fontSize: 14,
    color: '#6c757d',
  },
  hashtagsContainer: {
    padding: 20,
  },
  hashtagCard: {
    backgroundColor: '#e8f5f3',
    padding: 20,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: '#c3e9e2',
  },
  hashtagText: {
    fontSize: 16,
    color: '#00BFA5',
    fontWeight: '600',
    lineHeight: 24,
  },
  copyHint: {
    fontSize: 12,
    color: '#6c757d',
    marginTop: 5,
  },
  ctaContainer: {
    padding: 20,
    paddingBottom: 40,
  },
  ctaButton: {
    backgroundColor: '#000',
    paddingVertical: 18,
    borderRadius: 15,
    alignItems: 'center',
  },
  ctaButtonText: {
    color: 'white',
    fontSize: 18,
    fontWeight: '700',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  modalContent: {
    backgroundColor: 'white',
    borderRadius: 20,
    width: '100%',
    maxHeight: '90%',
    elevation: 5,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#e9ecef',
  },
  modalIcon: {
    fontSize: 30,
    marginRight: 10,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#212529',
    flex: 1,
  },
  closeButton: {
    width: 30,
    height: 30,
    justifyContent: 'center',
    alignItems: 'center',
  },
  closeButtonText: {
    fontSize: 24,
    color: '#6c757d',
  },
  modalScroll: {
    maxHeight: '100%',
  },
  modalScrollContent: {
    padding: 20,
    paddingBottom: 30,
    flexGrow: 1,
  },
  modalSectionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#212529',
    marginBottom: 10,
    marginTop: 20,
  },
  scriptBox: {
    backgroundColor: '#f8f9fa',
    padding: 15,
    borderRadius: 10,
    marginBottom: 20,
  },
  scriptText: {
    fontSize: 14,
    color: '#495057',
    lineHeight: 22,
  },
  tipItem: {
    fontSize: 14,
    color: '#495057',
    marginBottom: 8,
    lineHeight: 20,
  },
  hashtagBox: {
    backgroundColor: '#e8f5f3',
    padding: 15,
    borderRadius: 10,
    marginBottom: 20,
  },
  hashtagTextModal: {
    fontSize: 14,
    color: '#00BFA5',
    fontWeight: '600',
  },
  modalActions: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 20,
    gap: 10,
  },
  shareButton: {
    flex: 1,
    backgroundColor: '#8B5CF6',
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
  },
  shareButtonText: {
    color: 'white',
    fontSize: 16,
    fontWeight: '700',
  },
  createButton: {
    flex: 1,
    backgroundColor: '#00BFA5',
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
  },
  createButtonText: {
    color: 'white',
    fontSize: 16,
    fontWeight: '700',
  },
});