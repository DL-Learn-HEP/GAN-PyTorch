# Copyright 2020 Lorna Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Generative Adversarial Networks (GANs) are one of the most interesting ideas
in computer science today. Two models are trained simultaneously by
an adversarial process. A generator ("the artist") learns to create images
that look real, while a discriminator ("the art critic") learns
to tell real images apart from fakes.
"""

import argparse
import os
import random
import warnings

import matplotlib.pyplot as plt
import torch
import torch.backends.cudnn as cudnn
import torch.distributed as dist
import torch.multiprocessing as mp
import torch.nn as nn
import torch.nn.parallel
import torch.optim
import torch.utils.data
import torch.utils.data.distributed
import torchvision.datasets as datasets
import torchvision.transforms as transforms
import torchvision.utils as vutils
from dcgan_pytorch import weights_init
from tqdm import tqdm

from gan_pytorch import Discriminator
from gan_pytorch import Generator

parser = argparse.ArgumentParser(description='PyTorch GAN')
parser.add_argument('--dataroot', type=str, default='./data',
                    help='path to datasets')
parser.add_argument('name', type=str,
                    help='dataset name. Option: [mnist, fmnist]')
parser.add_argument('-g', '--generator-arch', metavar='STR',
                    help='generator model architecture')
parser.add_argument('-d', '--discriminator-arch', metavar='STR',
                    help='discriminator model architecture')
parser.add_argument('-j', '--workers', default=4, type=int, metavar='N',
                    help='number of data loading workers (default: 4)')
parser.add_argument('--epochs', default=200, type=int, metavar='N',
                    help='number of total epochs to run')
parser.add_argument('--start-epoch', default=0, type=int, metavar='N',
                    help='manual epoch number (useful on restarts)')
parser.add_argument('-b', '--batch-size', default=64, type=int,
                    metavar='N',
                    help='mini-batch size (default: 64), this is the total '
                         'batch size of all GPUs on the current node when '
                         'using Data Parallel or Distributed Data Parallel')
parser.add_argument('--lr', type=float, default=0.0002,
                    help='learning rate. (Default=0.0002)')
parser.add_argument('--beta1', type=float, default=0.5,
                    help='beta1 for adam. (Default=0.5)')
parser.add_argument('--beta2', type=float, default=0.999,
                    help='beta2 for adam. (Default=0.999)')
parser.add_argument('-p', '--print-freq', default=100, type=int,
                    metavar='N', help='print frequency (default: 100)')
parser.add_argument('--netG', default='', type=str, metavar='PATH',
                    help='path to latest generator checkpoint (default: none)')
parser.add_argument('--netD', default='', type=str, metavar='PATH',
                    help='path to latest discriminator checkpoint (default: none)')
parser.add_argument('--init-weights', action='store_true',
                    help='Using the initialization weight method in dcgan architecture')
parser.add_argument('-e', '--evaluate', dest='evaluate', action='store_true',
                    help='evaluate model on validation set')
parser.add_argument('--pretrained', dest='pretrained', action='store_true',
                    help='use pre-trained model')
parser.add_argument('--world-size', default=-1, type=int,
                    help='number of nodes for distributed training')
parser.add_argument('--rank', default=-1, type=int,
                    help='node rank for distributed training')
parser.add_argument('--dist-url', default='tcp://224.66.41.62:23456', type=str,
                    help='url used to set up distributed training')
parser.add_argument('--dist-backend', default='nccl', type=str,
                    help='distributed backend')
parser.add_argument('--outf', default='./imgs',
                    help='folder to output images. (default=`./imgs`).')
parser.add_argument('--seed', default=None, type=int,
                    help='seed for initializing training.')
parser.add_argument('--gpu', default=0, type=int,
                    help='GPU id to use.')
parser.add_argument('--multiprocessing-distributed', action='store_true',
                    help='Use multi-processing distributed training to launch '
                         'N processes per node, which has N GPUs. This is the '
                         'fastest way to use PyTorch for either single node or '
                         'multi node data parallel training')

fixed_noise = torch.randn(64, 100)


def main():
    args = parser.parse_args()
    print(args)

    try:
        os.makedirs(args.outf)
    except OSError:
        pass

    if args.seed is not None:
        random.seed(args.seed)
        torch.manual_seed(args.seed)
        cudnn.deterministic = True
        warnings.warn('You have chosen to seed training. '
                      'This will turn on the CUDNN deterministic setting, '
                      'which can slow down your training considerably! '
                      'You may see unexpected behavior when restarting '
                      'from checkpoints.')

    if args.gpu is not None:
        warnings.warn('You have chosen a specific GPU. This will completely '
                      'disable data parallelism.')

    if args.dist_url == "env://" and args.world_size == -1:
        args.world_size = int(os.environ["WORLD_SIZE"])

    args.distributed = args.world_size > 1 or args.multiprocessing_distributed

    ngpus_per_node = torch.cuda.device_count()
    if args.multiprocessing_distributed:
        # Since we have ngpus_per_node processes per node, the total world_size
        # needs to be adjusted accordingly
        args.world_size = ngpus_per_node * args.world_size
        # Use torch.multiprocessing.spawn to launch distributed processes: the
        # main_worker process function
        mp.spawn(main_worker, nprocs=ngpus_per_node, args=(ngpus_per_node, args))
    else:
        # Simply call main_worker function
        main_worker(args.gpu, ngpus_per_node, args)


def main_worker(gpu, ngpus_per_node, args):
    args.gpu = gpu

    if args.gpu is not None:
        print(f"Use GPU: {args.gpu} for training!")

    if args.distributed:
        if args.dist_url == "env://" and args.rank == -1:
            args.rank = int(os.environ["RANK"])
        if args.multiprocessing_distributed:
            # For multiprocessing distributed training, rank needs to be the
            # global rank among all the processes
            args.rank = args.rank * ngpus_per_node + gpu
        dist.init_process_group(backend=args.dist_backend, init_method=args.dist_url,
                                world_size=args.world_size, rank=args.rank)
    # create model
    if 'g' in args.generator_arch and 'd' in args.discriminator_arch:
        print("=> creating model")
        discriminator = Discriminator.from_name(args.discriminator_arch)
        generator = Generator.from_name(args.generator_arch)
        if args.init_weights:
            discriminator.apply(weights_init)
            generator.apply(weights_init)
    else:
        warnings.warn('You have chosen a specific model architecture. '
                      'This will default use MNIST model architecture and load pre-train model weights!')
        discriminator = Discriminator.from_pretrained('d-mnist')
        generator = Generator.from_pretrained('g-mnist')

    if args.pretrained:
        print("=> using pre-trained model")
        discriminator = Discriminator.from_pretrained(args.discriminator_arch)
        generator = Generator.from_pretrained(args.generator_arch)

    if args.distributed:
        # For multiprocessing distributed, DistributedDataParallel constructor
        # should always set the single device scope, otherwise,
        # DistributedDataParallel will use all available devices.
        if args.gpu is not None:
            torch.cuda.set_device(args.gpu)
            generator.cuda(args.gpu)
            discriminator.cuda(args.gpu)
            # When using a single GPU per process and per
            # DistributedDataParallel, we need to divide the batch size
            # ourselves based on the total number of GPUs we have
            args.batch_size = int(args.batch_size / ngpus_per_node)
            args.workers = int(args.workers / ngpus_per_node)
            generator = torch.nn.parallel.DistributedDataParallel(generator, device_ids=[args.gpu])
            discriminator = torch.nn.parallel.DistributedDataParallel(discriminator, device_ids=[args.gpu])
        else:
            generator.cuda()
            discriminator.cuda()
            # DistributedDataParallel will divide and allocate batch_size to all
            # available GPUs if device_ids are not set
            generator = torch.nn.parallel.DistributedDataParallel(generator)
            discriminator = torch.nn.parallel.DistributedDataParallel(discriminator)
    elif args.gpu is not None:
        torch.cuda.set_device(args.gpu)
        generator = generator.cuda(args.gpu)
        discriminator = discriminator.cuda(args.gpu)
    else:
        # DataParallel will divide and allocate batch_size to all available
        # GPUs
        generator = torch.nn.DataParallel(generator).cuda()
        discriminator = torch.nn.DataParallel(discriminator).cuda()

    # define loss function (adversarial_loss) and optimizer
    adversarial_loss = nn.BCELoss().cuda(args.gpu)

    optimizer_g = torch.optim.Adam(generator.parameters(), lr=args.lr, betas=(args.beta1, args.beta2))
    optimizer_d = torch.optim.Adam(discriminator.parameters(), lr=args.lr, betas=(args.beta1, args.beta2))

    # optionally resume from a checkpoint
    if args.netG:
        if os.path.isfile(args.netG):
            print(f"=> loading checkpoint `{args.netG}`")
            state_dict = torch.load(args.netG)
            generator.load_state_dict(state_dict)
            print(f"=> loaded checkpoint `{args.netG}`")
        else:
            print(f"=> no checkpoint found at `{args.netG}`")
    if args.netD:
        if os.path.isfile(args.netD):
            print(f"=> loading checkpoint `{args.netD}`")
            state_dict = torch.load(args.netD)
            discriminator.load_state_dict(state_dict)
            print(f"=> loaded checkpoint `{args.netD}`")
        else:
            print(f"=> no checkpoint found at '{args.netD}'")

    cudnn.benchmark = True

    if args.evaluate:
        validate(generator, args)
        return

    if args.name == 'mnist':
        dataset = datasets.MNIST(root=args.dataroot, download=True,
                                 transform=transforms.Compose([
                                     transforms.ToTensor(),
                                     transforms.Normalize((0.5,), (0.5,)),
                                 ]))
    elif args.name == 'fmnist':
        dataset = datasets.FashionMNIST(root=args.dataroot, download=True,
                                        transform=transforms.Compose([
                                            transforms.ToTensor(),
                                            transforms.Normalize((0.5,), (0.5,)),
                                        ]))
    else:
        warnings.warn('You have chosen a specific dataset. This will '
                      'default use MNIST dataset!')
        dataset = datasets.MNIST(root=args.dataroot, download=True,
                                 transform=transforms.Compose([
                                     transforms.ToTensor(),
                                     transforms.Normalize((0.5,), (0.5,)),
                                 ]))

    data_loader = torch.utils.data.DataLoader(dataset, batch_size=args.batch_size,
                                              shuffle=True, num_workers=int(args.workers))

    # Lists to keep track of progress
    g_losses = []
    d_losses = []
    for epoch in range(args.start_epoch, args.epochs):
        # train for one epoch
        train(data_loader, generator, discriminator, adversarial_loss, optimizer_g, optimizer_d, epoch, g_losses,
              d_losses, args)

        if not args.multiprocessing_distributed or (args.multiprocessing_distributed
                                                    and args.rank % ngpus_per_node == 0):
            # save checkpoint
            torch.save(generator.state_dict(), f"{args.outf}/netG_epoch_{epoch}.pth")
            torch.save(discriminator.state_dict(), f"{args.outf}/netD_epoch_{epoch}.pth")

        # save last checkpoint
        if epoch == args.epoochs - 1:
            torch.save(generator.state_dict(), f"{args.outf}/g.pth")
            torch.save(discriminator.state_dict(), f"{args.outf}/d.pth")

    plt.figure(figsize=(10, 5))
    plt.title("Generator and Discriminator Loss During Training")
    plt.plot(g_losses, label="G")
    plt.plot(d_losses, label="D")
    plt.xlabel("iterations")
    plt.ylabel("Loss")
    plt.legend()
    plt.savefig("result.png")


def train(data_loader, generator, discriminator, adversarial_loss, optimizer_g, optimizer_d, epoch, g_losses, d_losses,
          args):
    # switch to train mode
    global fixed_noise
    generator.train()
    discriminator.train()

    progress_bar = tqdm(enumerate(data_loader), total=len(data_loader))
    for i, data in progress_bar:
        # get batch size data
        real_images = data[0]
        if args.gpu is not None:
            real_images = real_images.cuda(args.gpu, non_blocking=True)
        batch_size = real_images.size(0)

        # real data label is 1, fake data label is 0.
        real_label = torch.full((batch_size, 1), 1)
        fake_label = torch.full((batch_size, 1), 0)
        # Sample noise as generator input
        noise = torch.randn(batch_size, 100)
        if args.gpu is not None:
            real_label = real_label.cuda(args.gpu, non_blocking=True)
            fake_label = fake_label.cuda(args.gpu, non_blocking=True)
            noise = noise.cuda(args.gpu, non_blocking=True)

        ##############################################
        # (1) Update D network: maximize log(D(x)) + log(1 - D(G(z)))
        ##############################################
        discriminator.zero_grad()

        # Train with real
        real_output = discriminator(real_images)
        errD_real = adversarial_loss(real_output, real_label)
        D_x = real_output.mean().item()

        # Generate fake image batch with G
        fake = generator(noise)

        # Train with fake
        fake_output = discriminator(fake.detach())
        errD_fake = adversarial_loss(fake_output, fake_label)
        D_G_z1 = fake_output.mean().item()

        # Add the gradients from the all-real and all-fake batches
        errD = (errD_real + errD_fake) / 2
        errD.backward()
        # Update D
        optimizer_d.step()

        ##############################################
        # (2) Update G network: maximize log(D(G(z)))
        ##############################################
        generator.zero_grad()

        fake_output = discriminator(fake)
        errG = adversarial_loss(fake_output, real_label)
        errG.backward()
        D_G_z2 = fake_output.mean().item()
        # Update G
        optimizer_g.step()

        progress_bar.set_description(f"[{epoch}/{args.epochs - 1}][{i}/{len(data_loader) - 1}] "
                                     f"Loss_D: {errD.item():.4f} "
                                     f"Loss_G: {errG.item():.4f} "
                                     f"D_x: {D_x:.4f} "
                                     f"D(G(z)): {D_G_z1:.4f} / {D_G_z2:.4f}")

        if i % args.print_freq == 0:
            vutils.save_image(real_images,
                              f"{args.outf}/real_samples.png",
                              normalize=True)

            # Save Losses for plotting later
            g_losses.append(errG.item())
            d_losses.append(errD.item())

            if args.gpu is not None:
                fixed_noise = fixed_noise.cuda(args.gpu, non_blocking=True)
            fake = generator(fixed_noise)
            vutils.save_image(fake.detach(),
                              f"{args.outf}/fake_samples_epoch_{epoch}.png",
                              normalize=True)


def validate(model, args):
    # switch to evaluate mode
    model.eval()

    with torch.no_grad():
        noise = torch.randn(args.batch_size, 100)
        if args.gpu is not None:
            noise = noise.cuda(args.gpu, non_blocking=True)
        fake = model(noise)
        vutils.save_image(fake.detach(), f"{args.outf}/fake.png", normalize=True)
    print("The fake image has been generated!")


if __name__ == '__main__':
    main()
