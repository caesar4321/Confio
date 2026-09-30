//
// Copyright Amazon.com Inc. or its affiliates.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0
//

import UIKit
import AVFoundation
import Vision
import Amplify
@_spi(PredictionsFaceLiveness) import AWSPredictionsPlugin

final class _LivenessViewController: UIViewController {
    let viewModel: FaceLivenessDetectionViewModel
    var previewLayer: CALayer?

    let faceShapeLayer = CAShapeLayer()
    var ovalExists = false
    var ovalRect: CGRect?
    var freshness = Freshness()
    let freshnessView = FreshnessView()
    var readyForOval = false

    init(
        viewModel: FaceLivenessDetectionViewModel
    ) {
        self.viewModel = viewModel
        super.init(nibName: nil, bundle: nil)
        viewModel.livenessViewControllerDelegate = self
        viewModel.normalizeFace = { [weak self] face in
            guard let self = self else { return face }
            return DispatchQueue.main.sync {
                face.normalize(width: self.view.frame.width, height: self.view.frame.width / 3 * 4)
            }
        }
    }
    
    deinit {
        guard let previewLayer = self.previewLayer else { return }
        previewLayer.removeFromSuperlayer()
        (previewLayer as? AVCaptureVideoPreviewLayer)?.session = nil
        self.previewLayer = nil
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        layoutSubviews()
        setupAVLayer()
    }

    override func viewDidLayoutSubviews() {
        previewLayer?.position = view.center
    }

    private func layoutSubviews() {
        freshnessView.translatesAutoresizingMaskIntoConstraints = false

        view.addSubview(freshnessView)
        NSLayoutConstraint.activate([
            freshnessView.topAnchor.constraint(equalTo: view.topAnchor),
            freshnessView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            freshnessView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            freshnessView.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])
        freshnessView.clearColors()
    }

    private func setupAVLayer() {
        guard previewLayer == nil else { return }
        let x = view.frame.minX
        let y = view.frame.minY
        let width = view.frame.width
        let height = width / 3 * 4
        let cameraFrame = CGRect(x: x, y: y, width: width, height: height)

        guard let avLayer = viewModel.configureCamera(withinFrame: cameraFrame) else {
            DispatchQueue.main.async { [weak self] in
                self?.viewModel.livenessState
                    .unrecoverableStateEncountered(.missingVideoPermission)
            }
            return
        }

        avLayer.position = view.center
        self.previewLayer = avLayer
        if let previewLayer = self.previewLayer {
            viewModel.cameraViewRect = previewLayer.frame
        }

        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.view.layer.insertSublayer(avLayer, at: 0)
            self.view.layoutIfNeeded()
            self.showPlaceholderOval(over: avLayer)

            self.viewModel.startSession()
        }
    }

    var runningFreshness = false
    var hasSentClientInformationEvent = false
    var challengeID = UUID().uuidString
    var initialFace: FaceDetection?
    var videoStartTimeStamp: UInt64?
    var faceMatchStartTime: UInt64?
    var freshnessEventsComplete = false
    var videoSentCount = 0
    var hasSentFinalEvent = false
    var hasSentEmptyFinalVideoEvent = false
    var ovalView: OvalView?
    // Confío patch: masks the camera from the first frame, until the session's
    // own oval arrives (drawOvalInCanvas), so the screen is always the circle.
    var placeholderOvalView: OvalView?

    func showPlaceholderOval(over layer: CALayer) {
        guard ovalView == nil, placeholderOvalView == nil else { return }
        let bounds = CGRect(origin: .zero, size: layer.frame.size)
        let width = bounds.width * 0.6
        let height = width * 1.5
        let placeholder = OvalView(
            frame: layer.frame,
            ovalFrame: CGRect(x: (bounds.width - width) / 2, y: (bounds.height - height) / 2,
                              width: width, height: height)
        )
        placeholder.center = layer.position
        placeholderOvalView = placeholder
        view.insertSubview(placeholder, belowSubview: freshnessView)
    }


    required init?(coder: NSCoder) { fatalError() }
}

extension _LivenessViewController: FaceLivenessViewControllerPresenter {
    func displaySingleFrame(uiImage: UIImage) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            guard let previewLayer = self.previewLayer else { return }
            let imageView = UIImageView(image: uiImage)
            imageView.frame = previewLayer.frame
            // Confío patch: keep the frozen frame under the oval mask, so the
            // screen stays the circle with the face until the check completes
            // instead of revealing a full-frame photo.
            if let mask = self.ovalView ?? self.placeholderOvalView, mask.superview === self.view {
                self.view.insertSubview(imageView, belowSubview: mask)
            } else {
                self.view.addSubview(imageView)
            }
            (previewLayer as? AVCaptureVideoPreviewLayer)?.session = nil
            previewLayer.removeFromSuperlayer()
            self.viewModel.stopRecording()
        }
    }

    func displayFreshness(colorSequences: [FaceLivenessSession.DisplayColor]) {
        self.ovalView?.setNeedsDisplay()
        DispatchQueue.main.async { [weak self] in
            self?.viewModel.livenessState.displayingFreshness()
        }
        self.freshness.showColorSequences(
            colorSequences,
            width: UIScreen.main.bounds.width,
            height: UIScreen.main.bounds.height,
            view: self.freshnessView,
            onNewColor: { [weak self] colorEvent in
                self?.viewModel.sendColorDisplayedEvent(colorEvent)
            },
            onComplete: { [weak self] in
                guard let self else { return }
                self.freshnessView.removeFromSuperview()

                self.viewModel.handleFreshnessComplete()
            }
        )
    }

    func drawOvalInCanvas(_ ovalRect: CGRect) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            guard let previewLayer = self.previewLayer else { return }

            let ovalView = OvalView(
                frame: previewLayer.frame,
                ovalFrame: ovalRect
            )
            self.ovalView = ovalView
            ovalView.center = previewLayer.position
            self.view.insertSubview(
                ovalView,
                belowSubview: self.freshnessView
            )
            self.placeholderOvalView?.removeFromSuperview()
            self.placeholderOvalView = nil

            self.ovalRect = ovalRect
            self.ovalExists = true
        }
    }
    
    func completeNoLightCheck() {
        self.viewModel.completeNoLightCheck()
    }
}
